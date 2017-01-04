from faker import Faker
from functools import wraps
from locust import HttpLocust, TaskSet, task
from random import randint, choice
from requests import Response

import base64
import json


'''Decorator to turn python exceptions into 500 responses'''
def exception_protect(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as e:
            response = Response()
            response.status_code = 404
            response.reason = str(e)
            response._content = str(e)
            return response
    return wrapper

def register(l):
    details = {
        "username": l.user.get('username'),
        "first_name": l.user.get('name').split(' ')[0],
        "last_name": l.user.get('name').split(' ')[1],
        "email": l.user.get('mail'),
        "password": l.password
    }
    return l.client.post("/register", json=details)

@exception_protect
def login(l):
    users = l.client.get("/customers").json().get("_embedded", {}).get("customer", [])
    user = [user for user in users if user.get('username') == l.user.get('username')]
    if not user:
        register(l)

    base64string = base64.encodestring('%s:%s' % (l.user.get('username'), l.password)).replace('\n', '')
    return l.client.get("/login", headers={"Authorization":"Basic %s" % base64string})

def create_card(l):
    data = {
        "longNum": Faker().credit_card_number(),
        "expires": Faker().credit_card_expire(start="now", end="+10y", date_format="%m/%y"),
        "ccv": Faker().credit_card_security_code()
    }
    return l.client.post("/cards", json=data)

def create_address(l):
    data = {
        "number": str(Faker().random_int(min=1, max=9999)),
        "street": Faker().street_name(),
        "city": Faker().city(),
        "postcode": Faker().postcode(),
        "country": Faker().country()
    }
    return l.client.post("/addresses", json=data)


'''
    Tasks related to the Catalogue Page
'''
class CataloguePage(TaskSet):

    @task(20)
    def catalogue(self):
        self.client.get("/category.html")

    @task(10)
    @exception_protect
    def filter(self):
        tags = self.client.get("/tags").json().get("tags")
        rand = randint(1, len(tags)-1)
        l = [choice(tags) for i in range(1, rand)]
        self.client.get("/category.html?tags={}".format('&'.join(l)))

    @task(5)
    def stop(self):
        self.interrupt()

    '''
        Tasks related to the catalogue item page
    '''
    @task(10)
    class ItemPage(TaskSet):

        @task(10)
        @exception_protect
        def item(self):
            response = self.client.get("/catalogue")
            catalogue = response.json()
            self.client.get("/detail.html?id={}".format(choice(catalogue).get('id')))

        @task(5)
        @exception_protect
        def order(self):
            catalogue = self.client.get("/catalogue").json()
            category_item = choice(catalogue)
            item_id = category_item["id"]
            self.client.post("/cart", json={"id": item_id, "quantity": randint(1, 100)})

        @task(5)
        def stop(self):
            self.interrupt()


'''
    Tasks related to the Carts Page
'''
class CartPage(TaskSet):
    tasks = {create_card:1, create_address:1}

    @task(10)
    def cart(self):
        self.client.get("/basket.html")

    @task(5)
    @exception_protect
    def delete_item(self):
        cart_items = self.client.get("/cart").json()
        if len(cart_items) > 0:
            item = choice(cart_items)
            self.client.delete("/cart/{}".format(item.get("itemId")))

    @task(5)
    @exception_protect
    def checkout(self):
        if self.client.cookies.get("logged_in"):
            create_card(self)
            create_address(self)
            with self.client.post("/orders", catch_response=True) as response:
                if response.status_code == 406:
                    # Check if the cost was too high
                    items = self.client.get("/cart").json()
                    total = sum([item.get("unitPrice", 0) * item.get("quantity", 0) for item in items])
                    if total > 100:
                        response.success()

    @task(5)
    def stop(self):
        self.interrupt()

'''
    Website related tasks

    * Index Page
    * Register/Login
    * Catalogue Page
        * Item Page
            * Add item to basket
            * Add item to wishlist
        * Filter socks
    * Cart Page
        * Remove item
        * Add/Update Address info
        * Add/Update Payment info
        * Update item
        * Checkout
'''
class WebTasks(TaskSet):
    tasks = {login:15, CataloguePage:10, CartPage:5}
    user = Faker().simple_profile()
    password = Faker().password()

    @task(20)
    def index(self):
        self.client.get("/")


'''
    Cart related API tasks

    GET /cart
    DELETE /cart
    DELETE /cart
    DELETE /cart/:id
    POST /cart
'''
class CartTasks(TaskSet):

    @task
    def get_cart(self):
        self.client.get("/cart")

    @task
    def delete_cart(self):
        self.client.delete("/cart")

    @task
    @exception_protect
    def delete_cart_item(self):
        response = self.post_cart()
        body_json = json.loads(response.request.body)
        self.client.delete("/cart/{}".format(body_json.get('id')))

    @task
    @exception_protect
    def post_cart(self):
        catalogue = self.client.get("/catalogue").json()
        category_item = choice(catalogue)
        item_id = category_item["id"]
        return self.client.post("/cart", json={"id": item_id, "quantity": randint(1, 100)})


'''
    Catalogue related API tasks

    GET /catalogue/images*
    GET /catalogue*
    GET /tags
'''
class CatalogueTasks(TaskSet):

    @task
    @exception_protect
    def get_catalogue_images(self):
        catalogue = self.client.get('/catalogue').json()
        image_urls = choice(catalogue).get('imageUrl')
        self.client.get('{}'.format(choice(image_urls)))

    @task
    def get_catalogue(self):
        self.client.get('/catalogue')

    @task
    def get_tags(self):
        self.client.get('/tags')


'''
    Order related API tasks

    GET /orders
    GET /orders/*
    POST /orders
'''
class OrdersTasks(TaskSet):
    user = Faker().simple_profile()
    password = Faker().password()

    @task
    def get_orders(self):
        login(self)
        self.post_orders()
        self.client.get('/orders')

    @task
    @exception_protect
    def post_orders(self):
        login(self)
        create_card(self)
        create_address(self)

        catalogue = self.client.get("/catalogue").json()
        category_item = choice(catalogue)
        item_id = category_item["id"]
        self.client.post("/cart", json={"id": item_id, "quantity": 1})

        with self.client.post('/orders', catch_response=True) as response:
            if response.status_code == 406:
                response.success()


'''
    User related API tasks

    GET /customers/:id
    GET /cards/:id
    GET /customers
    GET /addresses
    GET /cards
    POST /customers
    POST /addresses
    POST /cards
    DELETE /customers/:id
    DELETE /addresses/:id
    DELETE /cards/:id
    POST /register
    POST /login
'''
class UsersTasks(TaskSet):
    user = Faker().simple_profile()
    password = Faker().password()

    @task
    @exception_protect
    def get_customer_id(self):
        response = self.post_register()
        customer = response.json()
        return self.client.get('/customers/{}'.format(customer.get('id')))

    @task
    @exception_protect
    def get_cards_id(self):
        response = self.post_register()
        customer = response.json()
        self.client.get('/cards/{}'.format(customer.get('id')))

    @task
    def get_customers(self):
        self.client.get('/customers')

    @task
    def get_addresses(self):
        self.client.get('/addresses')

    @task
    def get_cards(self):
        self.client.get('/cards')

    @task
    def post_customers(self):
        user = Faker().simple_profile()
        password = Faker().password()
        data = {
            'firstName': user.get('name').split(' ')[0],
            'lastName': user.get('name').split(' ')[1],
            'email': user.get('mail'),
            'username': user.get('username'),
            'password': password,
        }
        self.client.post('/customers', json=data)

    @task
    def post_addresses(self):
        login(self)
        create_address(self)

    @task
    def post_cards(self):
        login(self)
        create_card(self)

    @task
    @exception_protect
    def delete_customer(self):
        response = self.post_register()
        customer = response.json()
        self.client.delete('/customers/{}'.format(customer.get('id')))

    @task
    @exception_protect
    def delete_addresses(self):
        response = self.post_register()
        customer = response.json()
        self.client.delete('/addresses/{}'.format(customer.get('id')))

    @task
    @exception_protect
    def delete_cards(self):
        response = self.post_register()
        customer = response.json()
        self.client.delete('/cards/{}'.format(customer.get('id')))

    @task
    def post_register(self):
        self.user = Faker().simple_profile()
        self.password = Faker().password()
        return register(self)

    @task
    def post_login(self):
        self.user = Faker().simple_profile()
        self.password = Faker().password()
        login(self)


'''
    Describe API based tasks
'''
class APITasks(TaskSet):
    tasks = [CartTasks, CatalogueTasks, OrdersTasks, UsersTasks]


'''
    Describe tasks that result in an error
'''
class ErrorHandlingTasks(TaskSet):

    @task
    def login_fail(self):
        base64string = base64.encodestring('%s:%s' % ("wrong_user", "no_pass")).replace('\n', '')
        with self.client.get("/login", headers={"Authorization":"Basic %s" % base64string}, catch_response=True) as response:
            if response.status_code == 401:
                response.success()

    @task
    def checkout_fail(self):
        with self.client.post("/orders", json={}, catch_response=True) as response:
            if response.status_code == 500:
                response.success()


class API(HttpLocust):
    task_set = APITasks
    min_wait = 3000
    max_wait = 15000

class Web(HttpLocust):
    task_set = WebTasks
    min_wait = 3000
    max_wait = 15000

class ErrorHandling(HttpLocust):
    task_set = ErrorHandlingTasks
    min_wait = 3000
    max_wait = 15000
