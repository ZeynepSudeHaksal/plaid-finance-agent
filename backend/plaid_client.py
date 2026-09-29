"""
Wrapper around Plaid's API for the three calls this app needs:

1. create_link_token   -> lets the frontend open Plaid Link (the bank-picker UI)
2. exchange_public_token -> turns Link's temporary token into a permanent access_token
3. sync_transactions    -> pulls transactions for a linked item

All calls run against Plaid's Sandbox environment by default, which
simulates real banks with realistic (fake) data - no real account needed.
"""
import os
from typing import Optional

import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest

PLAID_ENV_MAP = {
    "sandbox": plaid.Environment.Sandbox,
    "development": plaid.Environment.Development,
    "production": plaid.Environment.Production,
}


def _get_client() -> plaid_api.PlaidApi:
    configuration = plaid.Configuration(
        host=PLAID_ENV_MAP[os.getenv("PLAID_ENV", "sandbox")],
        api_key={
            "clientId": os.getenv("PLAID_CLIENT_ID"),
            "secret": os.getenv("PLAID_SECRET"),
        },
    )
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)


def create_link_token(user_id: str) -> str:
    """Create a short-lived token the frontend uses to open Plaid Link."""
    client = _get_client()
    request = LinkTokenCreateRequest(
        products=[Products("transactions")],
        client_name="Finance Agent",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
    )
    response = client.link_token_create(request)
    return response.link_token


def exchange_public_token(public_token: str) -> dict:
    """Exchange Link's temporary public_token for a permanent access_token."""
    client = _get_client()
    request = ItemPublicTokenExchangeRequest(public_token=public_token)
    response = client.item_public_token_exchange(request)
    return {
        "access_token": response.access_token,
        "item_id": response.item_id,
    }


def sync_transactions(access_token: str, cursor: Optional[str] = None) -> dict:
    """
    Pull transactions for a linked item using Plaid's /transactions/sync,
    which handles pagination and incremental updates for you.
    Returns added/modified/removed transactions plus a cursor to save
    for the next sync call.
    """
    client = _get_client()
    # Plaid's SDK rejects cursor=None outright (it wants the field
    # omitted entirely on the first call, not set to null) - so only
    # include it in the request when we actually have one.
    if cursor:
        request = TransactionsSyncRequest(access_token=access_token, cursor=cursor)
    else:
        request = TransactionsSyncRequest(access_token=access_token)
    response = client.transactions_sync(request)
    return {
        "added": response.added,
        "modified": response.modified,
        "removed": response.removed,
        "next_cursor": response.next_cursor,
        "has_more": response.has_more,
    }