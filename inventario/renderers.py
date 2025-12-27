from rest_framework.renderers import BaseRenderer

class XLSXRenderer(BaseRenderer):
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    format = "xlsx"
    charset = None  # binary

    def render(self, data, accepted_media_type=None, renderer_context=None):
        # data debe ser bytes
        if data is None:
            return b""
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        # Si por error llega dict/list, lo forzamos a bytes inválido (mejor fallar claro)
        raise TypeError("XLSXRenderer espera bytes (contenido del archivo).")