import os

import psycopg
from psycopg.rows import TupleRow

from pulse_frame.store.errors import StoreError

URL_VARIABLE = "PULSE_FRAME_DATABASE_URL"


def database_url() -> str:
    url = os.environ.get(URL_VARIABLE, "")
    if not url.strip():
        raise StoreError(
            "DATABASE_URL_MISSING",
            f"`{URL_VARIABLE}` is not set, so the session store does not know"
            " which database to use.",
            f"Set `{URL_VARIABLE}` in your shell to the local database's"
            " connection URL, then run the command again. It is read from the"
            " environment only, never from a file in the repo.",
        )
    return url


def connect() -> psycopg.Connection[TupleRow]:
    url = database_url()
    try:
        return psycopg.connect(url)
    except psycopg.ProgrammingError:
        raise StoreError(
            "DATABASE_URL_INVALID",
            f"`{URL_VARIABLE}` is not a connection URL the database driver can"
            " read, so no connection was tried.",
            f"Set `{URL_VARIABLE}` to a URL of the form"
            " postgresql://user@host:port/dbname, with only options Postgres"
            " knows, then run the command again.",
        ) from None
    except (psycopg.OperationalError, psycopg.InterfaceError) as error:
        raise StoreError(
            "DATABASE_UNAVAILABLE",
            f"The database named in `{URL_VARIABLE}` could not be reached or"
            f" refused the connection (SQLSTATE {error.sqlstate or 'none'}): it is"
            " not running, the URL points at the wrong place, or it turned the"
            " login away.",
            "Start the local database with `supabase start --workdir <repo>"
            " --network-id pulse-frame-local` (see"
            " pulse-frame-wiki/ecosystem/store.md), check"
            f" `{URL_VARIABLE}`, then run the command again.",
            error.sqlstate,
        ) from None
