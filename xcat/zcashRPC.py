#!/usr/bin/env python3

# Based on spend-p2sh-txout.py from python-bitcoinlib.
# Copyright (C) 2017 The Zcash developers

import sys
if sys.version_info.major < 3:
    sys.stderr.write('Sorry, Python 3.x required by this example.\n')
    sys.exit(1)

import zcash
import zcash.rpc
from zcash import SelectParams
from zcash.core import b2x, lx, x, b2lx, COIN, COutPoint, CMutableTxOut, CMutableTxIn, CMutableTransaction, Hash160
from zcash.core.script import CScript, OP_DUP, OP_IF, OP_ELSE, OP_ENDIF, OP_HASH160, OP_EQUALVERIFY, OP_CHECKSIG, SignatureHash, SIGHASH_ALL, OP_FALSE, OP_DROP, OP_CHECKLOCKTIMEVERIFY, OP_SHA256, OP_TRUE
from zcash.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from zcash.wallet import CBitcoinAddress, CBitcoinSecret, P2SHBitcoinAddress, P2PKHBitcoinAddress

from xcat.utils import *

# SelectParams('testnet')
SelectParams('regtest')
# TODO: accurately read user and pw info
# zcashd = zcash.rpc.Proxy(service_url="http://user:password@127.0.0.1:18232")
zcashd = zcash.rpc.Proxy(timeout=90)
FEE = 0.001*COIN

def x2s(hexstring):
    """Convert hex to a utf-8 string"""
    return binascii.unhexlify(hexstring).decode('utf-8')

def validateaddress(addr):
    return zcashd.validateaddress(addr)

def get_keys(funder_address, redeemer_address):
    fundpubkey = CBitcoinAddress(funder_address)
    redeempubkey = CBitcoinAddress(redeemer_address)
    return fundpubkey, redeempubkey

def privkey(address):
    zcashd.dumpprivkey(address)

def hashtimelockcontract(funder, redeemer, commitment, locktime):
    funderAddr = CBitcoinAddress(funder)
    redeemerAddr = CBitcoinAddress(redeemer)
    if type(commitment) == str:
        commitment = x(commitment)
    # h = sha256(secret)
    blocknum = zcashd.getblockcount()
    print("Current blocknum on Zcash: ", blocknum)
    redeemblocknum = blocknum + locktime
    print("Redeemblocknum on Zcash: ", redeemblocknum)
    # can rm op_dup and op_hash160 if you replace addrs with pubkeys (as raw hex/bin data?), and can rm last op_equalverify (for direct pubkey comparison)
    zec_redeemScript = CScript([OP_IF, OP_SHA256, commitment, OP_EQUALVERIFY,OP_DUP, OP_HASH160,
                                 redeemerAddr, OP_ELSE, redeemblocknum, OP_CHECKLOCKTIMEVERIFY, OP_DROP, OP_DUP, OP_HASH160,
                                 funderAddr, OP_ENDIF,OP_EQUALVERIFY, OP_CHECKSIG])
    # print("Redeem script for p2sh contract on Zcash blockchain: ", b2x(zec_redeemScript))
    txin_scriptPubKey = zec_redeemScript.to_p2sh_scriptPubKey()
    # Convert the P2SH scriptPubKey to a base58 Bitcoin address
    txin_p2sh_address = CBitcoinAddress.from_scriptPubKey(txin_scriptPubKey)
    p2sh = str(txin_p2sh_address)
    print("p2sh computed: ", p2sh)
    # Import address as soon as you create it
    zcashd.importaddress(p2sh, "", False)
    # Returning all this to be saved locally in p2sh.json
    return {'p2sh': p2sh, 'redeemblocknum': redeemblocknum, 'redeemScript': b2x(zec_redeemScript), 'redeemer': redeemer, 'funder': funder, 'locktime': locktime}

def fund_htlc(p2sh, amount):
    send_amount = float(amount)*COIN
    # Import addr at same time as you fund
    zcashd.importaddress(p2sh, "", False)
    fund_txid = zcashd.sendtoaddress(p2sh, send_amount)
    txid = b2x(lx(b2x(fund_txid)))
    return txid

# Following two functions are about the same
def check_funds(p2sh):
    zcashd.importaddress(p2sh, "", False)
    # Get amount in address
    amount = zcashd.getreceivedbyaddress(p2sh, 0)
    amount = amount/COIN
    return amount

def get_fund_status(p2sh):
    zcashd.importaddress(p2sh, "", False)
    amount = zcashd.getreceivedbyaddress(p2sh, 0)
    amount = amount/COIN
    print("Amount in zcash p2sh: ", amount, p2sh)
    if amount > 0:
        return 'funded'
    else:
        return 'empty'

def get_tx_details(txid):
    fund_txinfo = zcashd.gettransaction(txid)
    return fund_txinfo['details'][0]

def find_transaction_to_address(p2sh):
    zcashd.importaddress(p2sh, "", False)
    txs = zcashd.listunspent(0, 100)
    for tx in txs:
        if tx['address'] == CBitcoinAddress(p2sh):
            print("Found tx to p2sh", p2sh)
            return tx

def find_secret(p2sh, fundtx_input):
    txs = zcashd.call('listtransactions', "*", 20, 0, True)
    for tx in txs:
        raw = zcashd.gettransaction(lx(tx['txid']))['hex']
        decoded = zcashd.decoderawtransaction(raw)
        if('txid' in decoded['vin'][0]):
            sendid = decoded['vin'][0]['txid']
            if (sendid == fundtx_input ):
                print("Found funding tx: ", sendid)
                return parse_secret(lx(tx['txid']))
    print("Redeem transaction with secret not found")
    return

def parse_secret(txid):
    raw = zcashd.gettransaction(txid, True)['hex']
    decoded = zcashd.decoderawtransaction(raw)
    scriptSig = decoded['vin'][0]['scriptSig']
    asm = scriptSig['asm'].split(" ")
    pubkey = asm[1]
    secret = x2s(asm[2])
    redeemPubkey = P2PKHBitcoinAddress.from_pubkey(x(pubkey))
    return secret

def redeem_contract(contract, secret):
    # How to find redeemScript and redeemblocknum from blockchain?
    p2sh = contract.p2sh
    #checking there are funds in the address
    amount = check_funds(p2sh)
    if(amount == 0):
        print("Address ", p2sh, " not funded")
        quit()
    fundtx = find_transaction_to_address(p2sh)
    amount = fundtx['amount'] / COIN
    # print("Found fund_tx: ", fundtx)
    p2sh = P2SHBitcoinAddress(p2sh)
    if fundtx['address'] == p2sh:
        print("Found {0} in p2sh {1}, redeeming...".format(amount, p2sh))

        # Where can you find redeemblocknum in the transaction?
        # redeemblocknum = find_redeemblocknum(contract)
        blockcount = zcashd.getblockcount()
        print("\nCurrent blocknum at time of redeem on Zcash:", blockcount)
        if blockcount < contract.redeemblocknum:
            # TODO: parse the script once, up front.
            redeemPubKey = find_redeemAddr(contract)

            print('redeemPubKey', redeemPubKey)
            zec_redeemScript = CScript(x(contract.redeemScript))

            txin = CMutableTxIn(fundtx['outpoint'])
            txout = CMutableTxOut(fundtx['amount'] - FEE, redeemPubKey.to_scriptPubKey())
            # Create the unsigned raw transaction.
            tx = CMutableTransaction([txin], [txout])
            sighash = SignatureHash(zec_redeemScript, tx, 0, SIGHASH_ALL)
            # TODO: figure out how to better protect privkey
            privkey = zcashd.dumpprivkey(redeemPubKey)
            sig = privkey.sign(sighash) + bytes([SIGHASH_ALL])
            print("SECRET", secret)
            preimage = secret.encode('utf-8')
            txin.scriptSig = CScript([sig, privkey.pub, preimage, OP_TRUE, zec_redeemScript])
            txin_scriptPubKey = zec_redeemScript.to_p2sh_scriptPubKey()
            print('Raw redeem transaction hex: ', b2x(tx.serialize()))
            VerifyScript(txin.scriptSig, txin_scriptPubKey, tx, 0, (SCRIPT_VERIFY_P2SH,))
            print("Script verified, sending raw redeem transaction...")
            txid = zcashd.sendrawtransaction(tx)
            redeem_tx =  b2x(lx(b2x(txid)))
            fund_tx = str(fundtx['outpoint'])
            return  {"redeem_tx": redeem_tx, "fund_tx": fund_tx}
        else:
            print("nLocktime exceeded, refunding")
            refundPubKey = find_refundAddr(contract)
            print('refundPubKey', refundPubKey)
            txid = zcashd.sendtoaddress(refundPubKey, fundtx['amount'] - FEE)
            refund_tx =  b2x(lx(b2x(txid)))
            fund_tx = str(fundtx['outpoint'])
            return  {"refund_tx": refund_tx, "fund_tx": fund_tx}
    else:
        print("No contract for this p2sh found in database", p2sh)

def parse_script(script_hex):
    redeemScript = zcashd.decodescript(script_hex)
    scriptarray = redeemScript['asm'].split(' ')
    return scriptarray

def find_redeemblocknum(contract):
    print("In find_redeemblocknum")
    scriptarray = parse_script(contract.redeemScript)
    print("Returning scriptarray", scriptarray)
    redeemblocknum = scriptarray[8]
    return int(redeemblocknum)

def find_redeemAddr(contract):
    scriptarray = parse_script(contract.redeemScript)
    redeemer = scriptarray[6]
    redeemAddr = P2PKHBitcoinAddress.from_bytes(x(redeemer))
    return redeemAddr

def find_refundAddr(contract):
    scriptarray = parse_script(contract.redeemScript)
    funder = scriptarray[13]
    refundAddr = P2PKHBitcoinAddress.from_bytes(x(funder))
    return refundAddr

def find_recipient(contract):
    # make this dependent on actual fund tx to p2sh, not contract
    txid = contract.fund_tx
    raw = zcashd.gettransaction(lx(txid), True)['hex']
    decoded = zcashd.decoderawtransaction(raw)
    scriptSig = decoded['vin'][0]['scriptSig']
    print("Decoded", scriptSig)
    asm = scriptSig['asm'].split(" ")
    pubkey = asm[1]
    initiator = CBitcoinAddress(contract.initiator)
    fulfiller = CBitcoinAddress(contract.fulfiller)
    print("Initiator", b2x(initiator))
    print("Fulfiller", b2x(fulfiller))
    print('pubkey', pubkey)
    redeemPubkey = P2PKHBitcoinAddress.from_pubkey(x(pubkey))
    print('redeemPubkey', redeemPubkey)

def new_zcash_addr():
    addr = zcashd.getnewaddress()
    return str(addr)

def generate(num):
    blocks = zcashd.generate(num)
    return blocks
