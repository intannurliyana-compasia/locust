import os
import random
import time

from locust import FastHttpUser, task, between


class MarketplaceUser(FastHttpUser):
    host = os.getenv("MEDUSA_HOST", "https://project-ultra-api-dev-8kz1.compasia.com")

    connection_timeout = 30
    network_timeout = 60
    wait_time = between(1, 5)
    max_products_to_view = 5

    publishable_api_key = os.getenv(
        "MEDUSA_PUBLISHABLE_API_KEY",
        "pk_32e24f87d3d510be6576aeb3bc592bad79cbefb407b565a5196cbe85312a1c6b",
    )
    country_code = os.getenv("COUNTRY_CODE", "my")
    region_id = os.getenv("REGION_ID", "")
    cart_enabled = os.getenv("ENABLE_CART", "true").lower() == "true"
    checkout_enabled = os.getenv("ENABLE_CHECKOUT", "true").lower() == "true"

    headers = {
        "x-publishable-api-key": publishable_api_key,
        "Content-Type": "application/json",
    }

    @task(10)
    def all_deals_journey(self):
        promotions = self.list_promotions()
        time.sleep(random.uniform(2, 5))
        selected_deal = random.choice(promotions) if promotions else None

        # Deal data shape is backend-specific. Fall back to stable keywords if the
        # selected promotion does not expose a searchable title/code.
        query = self.get_deal_query(selected_deal)

        products = self.get_products_for_deal(query)
        if not products:
            return
        time.sleep(random.uniform(2, 5))

        viewed_products = []
        for product in random.sample(
            products, min(random.randint(1, self.max_products_to_view), len(products))
        ):
            product_detail = self.get_product_detail(product.get("id"))
            if product_detail:
                viewed_products.append(product_detail)
            time.sleep(random.uniform(3, 7))

        if not viewed_products or not self.cart_enabled or random.random() >= 0.10:
            return

        cart = self.create_cart()
        if not cart:
            return

        product = random.choice(viewed_products)
        variant_id = self.get_variant_id(product)
        if not variant_id:
            return

        line_item_added = self.add_line_item(cart["id"], variant_id)
        if not line_item_added:
            return

        if self.checkout_enabled and random.random() < 0.50:
            self.complete_checkout(cart["id"])

    def list_promotions(self):
        response = self.safe_get(
            "/store/promotions",
            headers=self.headers,
            name="All Deals - List Promotions",
            required=False,
        )
        if not response:
            return []

        data = self.parse_json(response)
        promotions = data.get("promotions") or data.get("data") or []
        if not isinstance(promotions, list):
            promotions = []
        return promotions

    def get_products_for_deal(self, query):
        products = []
        if query:
            products = self.search_products(query)
        if products:
            return products
        return self.list_products()

    def search_products(self, query):
        params = {
            "q": query,
            "limit": 12,
            "offset": random.choice([0, 6]),
        }

        response = self.safe_get(
            "/store/search/products",
            params=params,
            headers={"x-publishable-api-key": self.publishable_api_key},
            name="All Deals - Search Products",
            required=False,
        )
        if not response:
            return []

        data = self.parse_json(response)
        products = data.get("products") or data.get("hits") or data.get("data") or []
        if not isinstance(products, list):
            products = []
        return [product for product in products if isinstance(product, dict) and product.get("id")]

    def list_products(self):
        response = self.safe_get(
            "/store/products",
            params={"limit": 12},
            headers={"x-publishable-api-key": self.publishable_api_key},
            name="All Deals - Product Listing",
            required=False,
        )
        if not response:
            return []

        data = self.parse_json(response)
        products = data.get("products") or data.get("data") or []
        if not isinstance(products, list):
            products = []
        return [product for product in products if isinstance(product, dict) and product.get("id")]

    def get_product_detail(self, product_id):
        if not product_id:
            return None

        response = self.safe_get(
            f"/store/products/{product_id}",
            headers={"x-publishable-api-key": self.publishable_api_key},
            name="All Deals - Product Detail",
            required=False,
        )
        if not response:
            return None

        data = self.parse_json(response)
        return data.get("product") or data.get("data")

    def create_cart(self):
        payload = {"country_code": self.country_code}
        if self.region_id:
            payload["region_id"] = self.region_id

        with self.client.post(
            "/store/carts",
            json=payload,
            headers=self.headers,
            name="All Deals - Create Cart",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(
                    f"Unexpected status code: {response.status_code}. "
                    "Cart creation usually needs valid REGION_ID or backend-specific cart fields."
                )
                return None

            data = self.parse_json(response)
            cart = data.get("cart") or data.get("data")
            if not isinstance(cart, dict) or not cart.get("id"):
                response.failure("Cart payload missing id")
                return None
            return cart

    def add_line_item(self, cart_id, variant_id):
        payload = {
            "variant_id": variant_id,
            "quantity": 1,
        }
        with self.client.post(
            f"/store/carts/{cart_id}/line-items",
            json=payload,
            headers=self.headers,
            name="All Deals - Add Line Item",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(f"Unexpected status code: {response.status_code}")
                return False
        time.sleep(random.uniform(1, 2))
        return True

    def complete_checkout(self, cart_id):
        shipping_address_set = self.set_shipping_address(cart_id)
        if not shipping_address_set:
            return

        shipping_option_id = self.get_shipping_option_id(cart_id)
        if not shipping_option_id:
            return

        shipping_method_added = self.add_shipping_method(cart_id, shipping_option_id)
        if not shipping_method_added:
            return

        provider_id = self.get_payment_provider_id()
        if not provider_id:
            return

        payment_sessions_created = self.create_payment_sessions(cart_id)
        if not payment_sessions_created:
            return

        payment_session_set = self.set_payment_session(cart_id, provider_id)
        if not payment_session_set:
            return

        time.sleep(random.uniform(5, 10))
        with self.client.post(
            f"/store/carts/{cart_id}/complete",
            headers=self.headers,
            name="All Deals - Complete Cart",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(f"Unexpected status code: {response.status_code}")

    def set_shipping_address(self, cart_id):
        payload = {
            "shipping_address": {
                "first_name": "Load",
                "last_name": "Test",
                "address_1": "123 Main St",
                "city": "Kuala Lumpur",
                "country_code": self.country_code,
                "postal_code": "50000",
                "phone": "+60123456789",
            }
        }

        with self.client.post(
            f"/store/carts/{cart_id}",
            json=payload,
            headers=self.headers,
            name="All Deals - Set Shipping Address",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(f"Unexpected status code: {response.status_code}")
                return False
            return True

    def get_shipping_option_id(self, cart_id):
        with self.client.get(
            "/store/shipping-options",
            params={"cart_id": cart_id},
            headers={"x-publishable-api-key": self.publishable_api_key},
            name="All Deals - Get Shipping Options",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Unexpected status code: {response.status_code}")
                return None

            data = self.parse_json(response)
            options = data.get("shipping_options") or data.get("data") or []
            if not options:
                return None
            option = next((item for item in options if isinstance(item, dict) and item.get("id")), None)
            return option.get("id") if option else None

    def add_shipping_method(self, cart_id, option_id):
        payload = {"option_id": option_id}
        with self.client.post(
            f"/store/carts/{cart_id}/shipping-methods",
            json=payload,
            headers=self.headers,
            name="All Deals - Add Shipping Method",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(f"Unexpected status code: {response.status_code}")
                return False
            return True

    def get_payment_provider_id(self):
        params = {}
        if self.region_id:
            params["region_id"] = self.region_id

        with self.client.get(
            "/store/payment-providers",
            params=params,
            headers={"x-publishable-api-key": self.publishable_api_key},
            name="All Deals - List Payment Providers",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Unexpected status code: {response.status_code}")
                return None

            data = self.parse_json(response)
            providers = data.get("payment_providers") or data.get("data") or []
            if not providers:
                return None
            provider = next((item for item in providers if isinstance(item, dict) and item.get("id")), None)
            return provider.get("id") if provider else None

    def create_payment_sessions(self, cart_id):
        with self.client.post(
            f"/store/carts/{cart_id}/payment-sessions",
            headers=self.headers,
            name="All Deals - Create Payment Sessions",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(f"Unexpected status code: {response.status_code}")
                return False
            return True

    def set_payment_session(self, cart_id, provider_id):
        payload = {"provider_id": provider_id}
        with self.client.post(
            f"/store/carts/{cart_id}/payment-session",
            json=payload,
            headers=self.headers,
            name="All Deals - Set Payment Session",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(f"Unexpected status code: {response.status_code}")
                return False
            return True

    def get_variant_id(self, product):
        variants = product.get("variants") or []
        if not variants:
            return None

        variant = next((item for item in variants if isinstance(item, dict) and item.get("id")), None)
        return variant.get("id") if variant else None

    def get_deal_query(self, deal):
        if isinstance(deal, dict):
            for key in ("code", "title", "name"):
                value = deal.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def safe_get(self, path, headers, name, params=None, required=True, retries=1):
        last_response = None
        for attempt in range(retries + 1):
            with self.client.get(
                path,
                params=params,
                headers=headers,
                name=name,
                catch_response=True,
            ) as response:
                last_response = response
                if response.status_code == 200:
                    return response

                is_retryable = response.status_code in (0, 502, 503, 504)
                if is_retryable and attempt < retries:
                    response.success()
                    time.sleep(random.uniform(0.5, 1.5))
                    continue

                if required:
                    response.failure(f"Unexpected status code: {response.status_code}")
                else:
                    response.success()
                return None
        return last_response

    @staticmethod
    def parse_json(response):
        try:
            return response.json()
        except Exception:
            return {}
