from django.conf import settings


def square_environment(request):
    return {"SQUARE_ENVIRONMENT": settings.SQUARE_ENVIRONMENT}


def sirencon(request):
    # Easy way to grep through things we've disabled that need to be
    # factored in to upstream.
    return {
        "SC_FALSE": False,
    }
