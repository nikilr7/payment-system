from django.urls import path
from .views import create_payout, merchant_list, merchant_detail, merchant_topup

urlpatterns = [
    path("merchants",                merchant_list,    name="merchant_list"),
    path("merchants/<int:merchant_id>",        merchant_detail,  name="merchant_detail"),
    path("merchants/<int:merchant_id>/topup",  merchant_topup,   name="merchant_topup"),
    path("payouts",                  create_payout,    name="create_payout"),
]
