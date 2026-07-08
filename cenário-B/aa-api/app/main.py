from fastapi import FastAPI, HTTPException

app = FastAPI(title="Attribute Authority Demo")

ATTRIBUTES = {
    "bob": {
        "eduPersonEntitlement": [
            "urn:mace:gidlab.rnp.br:entitlement:projeto-a:read",
            "urn:mace:gidlab.rnp.br:entitlement:projeto-a:submit",
            "urn:mace:gidlab.rnp.br:entitlement:projeto-c:read"
        ]
    }
}

@app.get("/attributes/{user_id}")
def get_attributes(user_id: str):
    user_attributes = ATTRIBUTES.get(user_id)

    if user_attributes is None:
        raise HTTPException(status_code=404, detail="User not found")

    return user_attributes