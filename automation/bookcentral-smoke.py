"""Run inside BookCentral: verify authenticated tenant isolation without writes."""
import json
import os
from pathlib import Path
import uuid
import requests

base = os.environ['BREEZE_API_BASE_URL'].rstrip('/')
key = Path(os.environ['BREEZE_API_KEY_FILE']).read_text().strip()
payload = {'orgId': str(uuid.uuid4()), 'subject': 'Release verification tenant guard',
           'description': 'Automatic verification; no ticket should be created.',
           'priority': 'normal', 'submitterName': 'Release verification',
           'submitterEmail': 'release-verification@example.invalid'}
response = requests.post(base + os.environ['BREEZE_SUPPORT_TICKET_PATH'],
                         headers={'X-API-Key': key}, json=payload, timeout=30)
if response.status_code != 403 or response.json().get('error') != 'Access to this organization denied':
    raise RuntimeError('BookCentral authenticated tenant guard did not verify; HTTP ' + str(response.status_code))
print(json.dumps({'authenticatedIntegration': True, 'crossOrganizationDenied': True, 'ticketsCreated': 0}))
