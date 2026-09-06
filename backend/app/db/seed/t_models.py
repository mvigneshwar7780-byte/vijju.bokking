from pydantic import BaseModel
class product(BaseModel):

    id: int
    name: str
    price: float
    quantity: int
