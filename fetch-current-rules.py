#!/usr/bin/env python3
"""fetch-current-rules.py — READ-ONLY. Print the live Firestore security rules for the project."""
import json
import google.auth
from google.oauth2 import service_account
import google.auth.transport.requests as gt
import requests

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
PROJECT = 'hk-portfolio-sync'
SCOPES = ['https://www.googleapis.com/auth/firebase', 'https://www.googleapis.com/auth/cloud-platform']

creds = service_account.Credentials.from_service_account_file(CRED, scopes=SCOPES)
creds.refresh(gt.Request())
H = {'Authorization': f'Bearer {creds.token}'}

# current release for firestore
r = requests.get(f'https://firebaserules.googleapis.com/v1/projects/{PROJECT}/releases/cloud.firestore', headers=H)
print('=== release lookup ===', r.status_code)
print(r.text[:600])
if r.status_code != 200:
    raise SystemExit('cannot read release')
ruleset_name = r.json().get('rulesetName')
print('\nrulesetName =', ruleset_name)

rs = requests.get(f'https://firebaserules.googleapis.com/v1/{ruleset_name}', headers=H)
print('\n=== current ruleset source ===', rs.status_code)
data = rs.json()
for f in data.get('source', {}).get('files', []):
    print(f"\n----- {f.get('name')} -----")
    print(f.get('content'))
