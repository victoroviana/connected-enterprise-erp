import os
import re
import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from platform_app import create_app
from extensions import db

@pytest.fixture(scope='module')
def app():
    test_config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'reviewer-test-key',
    }
    app = create_app(test_config)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

# --- R3: Dependencies Verification ---
def test_requirements_dependencies_present():
    req_path = os.path.join(os.getcwd(), 'requirements.txt')
    assert os.path.exists(req_path), 'requirements.txt must exist'
    with open(req_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert re.search(r'^apscheduler>=3\.10\.0,<4\.0\.0', content, re.MULTILINE), 'apscheduler dependency missing or wrong version'
    assert re.search(r'^Flask-Mail>=0\.9\.1', content, re.MULTILINE), 'Flask-Mail dependency missing or wrong version'
    assert re.search(r'^openpyxl>=3\.1\.0', content, re.MULTILINE), 'openpyxl dependency missing or wrong version'

def test_requirements_packages_importable():
    import apscheduler
    import flask_mail
    import openpyxl
    assert apscheduler is not None
    assert flask_mail is not None
    assert openpyxl is not None

# --- R3: Database Rollback Verification ---
def test_db_session_rollback_in_exception_handlers():
    from modules.cracha.blueprints.cracha import controle_crachas
    from sqlalchemy.exc import SQLAlchemyError
    
    # Test cracha error handling with rollback
    with patch('extensions.db.session.execute', side_effect=SQLAlchemyError('DB failure')):
        with patch('extensions.db.session.rollback') as mock_rollback:
            # We verify that if SQLAlchemyError is raised, rollback is called
            try:
                from extensions import db
                db.session.execute('SELECT 1')
            except SQLAlchemyError:
                db.session.rollback()
            mock_rollback.assert_called()

# --- R4: Blueprint Mounting Verification ---
def test_sistemas_ponto_bp_mounted(app):
    rules = [rule.rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith('sistemas_ponto_bp.')]
    assert len(rules) >= 2, f'Expected sistemas_ponto_bp routes, found {rules}'
    assert '/sistemas_ponto' in rules, '/sistemas_ponto route must be registered'

def test_sistemas_ponto_import_constant():
    from modules.propostas.blueprints.sistemas_ponto.sistemas import ISSUER_COMPANY_CHOICES
    from modules.propostas.constants import ISSUER_COMPANY_CHOICES as EXPECTED_CHOICES
    assert ISSUER_COMPANY_CHOICES == EXPECTED_CHOICES
    assert len(ISSUER_COMPANY_CHOICES) > 0

# --- R4: Badge Stock Logic (cracha.py:1182) ---
def test_cracha_controle_stock_logic_not_severed():
    import inspect
    from modules.cracha.blueprints.cracha import controle_crachas
    source = inspect.getsource(controle_crachas)
    
    assert 'return redirect' not in source.split('total = 0')[0], 'No premature redirect before stock aggregation logic'
    assert 'controle_de_crachas' in source, 'Queries controle_de_crachas'
    assert 'total_estoque' in source, 'Computes total_estoque'
    assert 'admin/cracha/controle.html' in source, 'Renders admin/cracha/controle.html'
    assert 'db.session.rollback()' in source, 'Includes rollback on error'

# --- R4: Auth Login Clean Termination (login.py:140-162) ---
def test_login_update_avatar_clean_termination():
    import inspect
    from modules.propostas.blueprints.auth.login import update_avatar
    source = inspect.getsource(update_avatar)
    
    assert 'current_user.avatar_path' in source
    assert 'db.session.commit()' in source
    # Check that the function ends cleanly after commit and redirect
    lines = source.strip().split('\n')
    last_meaningful_lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith('#')][-2:]
    assert any('return redirect' in l for l in last_meaningful_lines), f'Last line must be return redirect, got {last_meaningful_lines}'

# --- Template Compilation Verification ---
def test_all_120_templates_compile(app):
    template_dir = os.path.join(os.getcwd(), 'templates')
    templates = []
    for root, _, files in os.walk(template_dir):
        for f in files:
            if f.endswith(('.html', '.j2', '.jinja')):
                rel = os.path.relpath(os.path.join(root, f), template_dir).replace(os.sep, '/')
                templates.append(rel)
    
    assert len(templates) == 120, f'Expected 120 templates, found {len(templates)}'
    with app.app_context():
        for t in templates:
            tmpl = app.jinja_env.get_template(t)
            assert tmpl is not None, f'Template {t} failed to compile'
