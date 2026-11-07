#!/bin/bash
mkdir -p /logs/verifier
python3 -I /tests/verify.py
[ -s /logs/verifier/reward.txt ] || echo 0 > /logs/verifier/reward.txt
