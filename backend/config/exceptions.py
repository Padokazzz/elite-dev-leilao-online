from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    """Handler DRF que traduz rate limits (429) para português.

    Todas as outras respostas de erro passam intactas pelo handler
    padrão; só Throttled ganha mensagem em PT — antes o usuário via
    "Request was throttled." na tela de login. O header Retry-After é
    setado pelo próprio DRF e é mantido; `available_in` (segundos)
    também segue no corpo para o cliente exibir o tempo de espera.
    """

    response = drf_exception_handler(exc, context)

    if response is not None and isinstance(exc, Throttled):
        detail = "Muitas tentativas em pouco tempo."
        if exc.wait:
            detail += f" Tente de novo em ~{int(exc.wait)} segundos."
        else:
            detail += " Aguarde um minuto e tente de novo."
        response.data = {"detail": detail, "available_in": exc.wait}

    return response
