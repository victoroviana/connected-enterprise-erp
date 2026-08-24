from urllib.error import HTTPError, URLError

import pytest

from api import _CNPJNotFoundError, _CNPJServiceError, _fetch_cnpj_payload


class _FakeHeaders:
    def __init__(self, charset='utf-8'):
        self._charset = charset

    def get_content_charset(self):
        return self._charset


class _FakeResponse:
    def __init__(self, payload: bytes, charset: str = 'utf-8'):
        self._payload = payload
        self.headers = _FakeHeaders(charset)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._payload


def test_fetch_cnpj_payload_success_uses_standard_library():
    expected = {'razao_social': 'Empresa XYZ', 'cnpj': '123'}

    def _opener(req, timeout):  # noqa: ANN001 - assinatura definida pela função
        assert req.full_url.endswith('/12345678901234')
        assert timeout == 6
        return _FakeResponse(b'{"razao_social": "Empresa XYZ", "cnpj": "123"}')

    data = _fetch_cnpj_payload('12345678901234', opener=_opener)
    assert data == expected


def test_fetch_cnpj_payload_translates_http_404_into_specific_error():
    def _opener(req, timeout):  # noqa: ANN001 - assinatura definida pela função
        raise HTTPError(req.full_url, 404, 'Not Found', hdrs=None, fp=None)

    with pytest.raises(_CNPJNotFoundError):
        _fetch_cnpj_payload('12345678901234', opener=_opener)


def test_fetch_cnpj_payload_wraps_other_errors():
    def _opener(req, timeout):  # noqa: ANN001 - assinatura definida pela função
        raise URLError('boom')

    with pytest.raises(_CNPJServiceError):
        _fetch_cnpj_payload('12345678901234', opener=_opener)
