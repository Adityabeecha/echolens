"""Confirmed API boundary regressions from TypeSafe follow-up triage."""
import time

import pytest
from sqlalchemy import select

from echolens.config import settings
from echolens.db.models import CollectorState, Finding, Product
from tests.test_v8_scoping import client  # noqa: F401


def test_guest_snapshot_cannot_bypass_scope_with_product_name(client, monkeypatch):
    tc, ids, Session = client
    with Session() as session:
        session.get(Product, ids['Alpha']).is_demo = True
        session.commit()
    monkeypatch.setattr(settings, 'echolens_env', 'production')
    monkeypatch.setattr(settings, 'allow_guest', True)
    monkeypatch.setattr(settings, 'guest_demo_only', True)
    assert tc.get('/snapshot?product=Beta').status_code == 404
    assert tc.get('/snapshot?product=Alpha').status_code == 200


def test_manual_issue_uses_selected_products_repo(client, monkeypatch):
    import echolens.integrations.github_issue as gh
    tc, ids, Session = client
    with Session() as session:
        for name in ('Alpha', 'Beta'):
            session.add(CollectorState(source='github', identifier=f'owner/{name}',
                                       enabled=True, product_id=ids[name]))
        fid = session.scalar(select(Finding.id).where(Finding.product_id == ids['Beta']))
        session.commit()
    monkeypatch.setattr(settings, 'github_default_repo', 'owner/Alpha')
    monkeypatch.setattr(gh, 'create_issue', lambda repo, title, body: {'url': f'https://github.com/{repo}/issues/42'})
    response = tc.post(f'/findings/{fid}/github-issue?product_id={ids["Beta"]}')
    assert response.status_code == 200
    assert response.json()['repo'] == 'owner/Beta'


@pytest.mark.parametrize('fallback', ['', 'owner/explicit-default'])
def test_manual_issue_never_infers_another_products_repo(client, monkeypatch, fallback):
    import echolens.integrations.github_issue as gh
    tc, ids, Session = client
    with Session() as session:
        session.add(CollectorState(source='github', identifier='owner/Alpha',
                                   enabled=True, product_id=ids['Alpha']))
        fid = session.scalar(select(Finding.id).where(Finding.product_id == ids['Beta']))
        session.commit()
    monkeypatch.setattr(settings, 'github_default_repo', fallback)
    posted = []

    def create_issue(repo, title, body):
        posted.append(repo)
        return {'url': f'https://github.com/{repo}/issues/42'}

    monkeypatch.setattr(gh, 'create_issue', create_issue)
    response = tc.post(f'/findings/{fid}/github-issue?product_id={ids["Beta"]}')
    assert response.status_code == (200 if fallback else 422)
    assert posted == ([fallback] if fallback else [])


@pytest.mark.parametrize('issuer', ['accounts.google.com', 'https://accounts.google.com'])
def test_google_accepts_both_verified_issuer_forms(monkeypatch, issuer):
    from cryptography.hazmat.primitives.asymmetric import rsa
    import jwt
    from jwt.algorithms import RSAAlgorithm
    from echolens import google_auth
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(settings, 'google_client_id', 'test-client')
    # Supply a local public key at the network boundary; signature/claims remain real.
    public = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public['kid'] = 'local-key'
    monkeypatch.setattr(google_auth, '_keys', lambda force=False: {'keys': [public]})
    token = jwt.encode({'iss': issuer, 'aud': 'test-client', 'exp': int(time.time()) + 60,
                        'sub': '123', 'email': 'user@example.com', 'email_verified': True},
                       key, algorithm='RS256', headers={'kid': 'local-key'})
    assert google_auth.verify_id_token(token)['email'] == 'user@example.com'


def test_staging_does_not_allow_anonymous_admin_bootstrap(client, monkeypatch):
    tc, _, _ = client
    monkeypatch.setattr(settings, 'echolens_env', 'staging')
    response = tc.post('/auth/signup', json={'email': 'stranger@example.com', 'password': 'password'})
    assert response.status_code == 403
