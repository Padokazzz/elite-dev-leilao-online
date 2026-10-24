class BidRejected(Exception):
    """Lance recusado por uma regra de negócio.

    `code` é estável e pensado para a interface: o front-end mapeia cada
    código para a sua própria mensagem, sem depender do texto em PT-BR
    e sem quebrar se o texto mudar.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict:
        return {"code": self.code, "detail": self.message}