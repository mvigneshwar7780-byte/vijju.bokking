from fastapi import FastAPI 
from t_models import product

app = FastAPI()

products = [
    product(id=1, name="tree", price=10.99, quantity=10),
    product(id=2, name="toy", price=19.99, quantity=5),
    product(id=3, name="book", price=5.99, quantity=20),
]

@app.get("/")
def greet():
    return "Hello, World!"

@app.get("/products")
def get_all_products():
    return products

@app.get("/products/{id}")
def get_product_by_id(id: int):
    for product in products:
        if product.id == id:
            return product
    return {"error": "Product not found"}

@app.post("/products")
def add_product(product: product):
    products.append(product)
    return product

@app.put("/products")
def update_product(updated_product: product):
    for product in products:
        if product.id == updated_product.id:
            product = updated_product
            return product

    return "product not found"

@app.delete("/products/{id}")
def delete_product(id: int):
    for product in products:
        if product.id == id:
            products.remove(product)
            return "product deleted successfuly"
    return "product not found"
        