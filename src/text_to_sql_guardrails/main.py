from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .db import get_session
from .models import Item

app = FastAPI(title="text-to-sql-guardrails")
SessionDep = Annotated[Session, Depends(get_session)]


class ItemIn(BaseModel):
    name: str


class ItemOut(ItemIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/items", response_model=ItemOut, status_code=201)
def create_item(body: ItemIn, session: SessionDep) -> Item:
    item = Item(name=body.name)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@app.get("/items/{item_id}", response_model=ItemOut)
def get_item(item_id: int, session: SessionDep) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item
