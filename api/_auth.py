import os


def authorized(request):
    expected = os.environ.get("AGENT_TOKEN")
    if not expected:
        return False

    header = request.headers.get("authorization", "")
    return header == f"Bearer {expected}"
