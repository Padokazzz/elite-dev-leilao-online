import html
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.utils.html import strip_tags


API_BASE_URL = "https://api.artic.edu/api/v1"
SOURCE_NAME = "artic"
REQUEST_TIMEOUT = 5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MiB

ARTWORK_FIELDS = (
    "id,title,artist_display,date_display,medium_display,"
    "image_id,is_public_domain,description,dimensions"
)


class ArtworkAPIError(Exception):
    """Falha ao consultar ou interpretar a API do museu."""


def _request_json(url):
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "leilao-online/1.0",
            "AIC-User-Agent": "leilao-online/1.0",
        },
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)

            if len(body) > MAX_RESPONSE_BYTES:
                raise ArtworkAPIError(
                    "A resposta do catálogo externo excedeu o tamanho permitido."
                )

            payload = json.loads(body.decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise ArtworkAPIError(
            "Não foi possível consultar o catálogo externo."
        ) from exc

    if not isinstance(payload, dict):
        raise ArtworkAPIError("A API retornou uma resposta inválida.")

    return payload



def iiif_image_url(image_id, size=843):
    """Monta a URL oficial IIIF do ArtIC para um image_id validado."""
    return (
        "https://www.artic.edu/iiif/2/"
        f"{image_id}/full/{size},/0/default.jpg"
    )


def _normalize_artwork(artwork):
    if not isinstance(artwork, dict):
        raise ArtworkAPIError("A API retornou uma obra inválida.")

    artwork_id = artwork.get("id")
    title = artwork.get("title")

    if (
        isinstance(artwork_id, bool)
        or not isinstance(artwork_id, int)
        or artwork_id <= 0
        or not isinstance(title, str)
        or not title.strip()
    ):
        raise ArtworkAPIError(
            "A obra não possui identificador ou título válido."
        )

    image_id = artwork.get("image_id")
    image_url = ""
    safe_image_id = ""

    if (
        isinstance(image_id, str)
        and image_id.strip()
        and len(image_id) <= 100
        and "/" not in image_id
        and "\\" not in image_id
        and not any(char.isspace() for char in image_id)
    ):
        safe_image_id = image_id
        image_url = iiif_image_url(image_id)

    # O ArtIC devolve descrição em HTML (<p>, <em>…); o contrato do
    # nosso campo é texto puro — remove as tags, resolve entidades
    # (&amp;, &hellip;) e normaliza espaços.
    raw_description = artwork.get("description") or ""
    if not isinstance(raw_description, str):
        raw_description = ""
    description = " ".join(
        html.unescape(strip_tags(raw_description)).split()
    )

    return {
        "id": str(artwork_id),
        "title": title.strip(),
        "description": description,
        "image_url": image_url,
        "image_id": safe_image_id,
        "attributes": {
            "artist": artwork.get("artist_display") or "Artista desconhecido",
            "date": artwork.get("date_display") or "",
            "medium": artwork.get("medium_display") or "",
            "dimensions": artwork.get("dimensions") or "",
            "is_public_domain": artwork.get("is_public_domain") is True,
            "source_url": f"https://www.artic.edu/artworks/{artwork_id}",
        },
    }


def fetch_artwork_image(url):
    request = Request(
        url,
        headers={
            "Accept": "image/*",
            "User-Agent": "leilao-online/1.0",
            "AIC-User-Agent": "leilao-online/1.0",
        },
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            content_type = response.headers.get(
                "Content-Type", "application/octet-stream"
            )
            body = response.read(MAX_RESPONSE_BYTES + 1)

            if len(body) > MAX_RESPONSE_BYTES:
                raise ArtworkAPIError(
                    "A imagem do catálogo externo excedeu o tamanho permitido."
                )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise ArtworkAPIError(
            "Não foi possível baixar a imagem do catálogo externo."
        ) from exc

    return content_type, body


def search_artworks(query, limit=10):
    query = query.strip()

    if not query:
        raise ValueError("Informe um termo para pesquisar.")

    if len(query) > 100:
        raise ValueError("A pesquisa deve ter no máximo 100 caracteres.")

    if not 1 <= limit <= 20:
        raise ValueError("O limite deve estar entre 1 e 20.")

    params = {
        "q": query,
        "size": limit,
        "fields": ARTWORK_FIELDS,
        "query": {"term": {"is_public_domain": True}},
    }

    url = (
        f"{API_BASE_URL}/artworks/search?"
        f"{urlencode({'params': json.dumps(params)})}"
    )
    payload = _request_json(url)

    data = payload.get("data")
    config = payload.get("config") or {}

    if not isinstance(data, list):
        raise ArtworkAPIError("A API retornou uma lista de obras inválida.")

    return [
    _normalize_artwork(item)
    for item in data
    if isinstance(item, dict) and item.get("is_public_domain") is True
]


def get_artwork(external_id):
    if not external_id.isdigit():
        raise ValueError("O identificador da obra deve ser numérico.")

    params = urlencode({"fields": ARTWORK_FIELDS})
    url = f"{API_BASE_URL}/artworks/{external_id}?{params}"
    payload = _request_json(url)

    artwork = payload.get("data")
    config = payload.get("config") or {}

    if not isinstance(artwork, dict):
        raise ArtworkAPIError("A API não retornou os dados da obra.")

    if artwork.get("is_public_domain") is not True:
        raise ValueError(
            "Somente obras em domínio público podem ser importadas."
        )

    return _normalize_artwork(artwork)
