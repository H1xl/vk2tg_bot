"""
SSL helper for outbound HTTP (VK API + media downloads)
Помощник SSL для исходящих HTTP-запросов

aiohttp's ``ssl=True`` relies on Python's default SSL context, which on Windows
(and other environments without a system CA bundle wired into Python) often
fails with "unable to get local issuer certificate". Backing the context with
the ``certifi`` CA bundle fixes that while keeping certificate verification ON.

aiohttp ``ssl=True`` берёт системный CA-бандл, которого на Windows у Python часто
нет → ошибка проверки сертификата. Используем CA-бандл из ``certifi``, сохраняя
проверку сертификатов включённой.
"""

import ssl

import certifi

import config

# Build the verifying context once and reuse it (creating it per request is wasteful).
# Контекст создаётся один раз и переиспользуется.
_ssl_context: "ssl.SSLContext | None" = None


def get_ssl_param():
    """
    Return the value to pass as aiohttp's ``ssl=`` argument.

    * verify_ssl on  -> a certifi-backed SSLContext (verification stays ON, works
      even where Python can't find the system CA bundle).
    * verify_ssl off -> False (verification disabled — tests / self-signed only).
    """
    if not config.config.verify_ssl:
        return False

    global _ssl_context
    if _ssl_context is None:
        _ssl_context = ssl.create_default_context(cafile=certifi.where())
    return _ssl_context
