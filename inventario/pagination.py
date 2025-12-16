from rest_framework.pagination import PageNumberPagination

class Default30Pagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = "page_size"  # opcional (si quieres permitir cambiar)
    max_page_size = 200
