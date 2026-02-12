RUPEE = "\u20b9"

plants = {
    "snake-plant": {
        "id": "snake-plant",
        "name": "Snake Plant (Sansevieria)",
        "category": "Indoor",
        "description": "Low maintenance, air purifier",
        "price": f"{RUPEE}179",
        "image": "snake-plant.jpg",
    },
    "peace-lily": {
        "id": "peace-lily",
        "name": "Peace Lily (Spathiphyllum)",
        "category": "Indoor",
        "description": "Elegant white flowers, great for indoors",
        "price": f"{RUPEE}249",
        "image": "peace lily.jpg",
    },
    "spider-plant": {
        "id": "spider-plant",
        "name": "Spider Plant (Chlorophytum comosum)",
        "category": "Indoor",
        "description": "Fast-growing, easy to propagate",
        "price": f"{RUPEE}359",
        "image": "spider plant.jpg",
        "offer": True,
    },
    "hibiscus": {
        "id": "hibiscus",
        "name": "Hibiscus",
        "category": "Outdoor",
        "description": "Bright flowers, attracts pollinators",
        "price": f"{RUPEE}199",
        "image": "hibiscus plant.jpg",
    },
    "bougainvillea": {
        "id": "bougainvillea",
        "name": "Bougainvillea",
        "category": "Outdoor",
        "description": "Colorful, drought-resistant",
        "price": f"{RUPEE}499",
        "image": "Bougainvillea plant.jpg",
        "offer": True,
    },
    "rose": {
        "id": "rose",
        "name": "Rose (Varieties)",
        "category": "Outdoor",
        "description": "Classic beauty, high demand",
        "price": f"{RUPEE}199",
        "image": "rose plant.jpg",
        "new": True,
    },
    "lantana": {
        "id": "lantana",
        "name": "Lantana",
        "category": "Outdoor",
        "description": "Hardy, vibrant blooms",
        "price": f"{RUPEE}179",
        "image": "Lantana Plant.jpg",
    },
    "tulsi": {
        "id": "tulsi",
        "name": "Tulsi (Holy Basil)",
        "category": "Herbs",
        "description": "Sacred, medicinal, highly popular",
        "price": f"{RUPEE}149",
        "image": "tulsi plant.jpg",
        "offer": True,
    },
    "mint": {
        "id": "mint",
        "name": "Mint",
        "category": "Herbs",
        "description": "Easy to grow, strong aroma",
        "price": f"{RUPEE}150",
        "image": "mint plant.jpg",
    },
    "aloe-vera": {
        "id": "aloe-vera",
        "name": "Aloe Vera",
        "category": "Herbs",
        "description": "Medicinal, drought-tolerant",
        "price": f"{RUPEE}199",
        "image": "alovera plant.jpg",
        "new": True,
    },
    "curry-leaf": {
        "id": "curry-leaf",
        "name": "Curry Leaf Plant",
        "category": "Herbs",
        "description": "Popular in Indian households",
        "price": f"{RUPEE}139",
        "image": "curry leaf plant.jpg",
    },
    "lemongrass": {
        "id": "lemongrass",
        "name": "Lemongrass",
        "category": "Herbs",
        "description": "Fragrant and medicinal",
        "price": f"{RUPEE}179",
        "image": "lemongrass plant.jpg",
        "offer": True,
    },
    "jasmine": {
        "id": "jasmine",
        "name": "Jasmine (Mogra)",
        "category": "Flowering",
        "description": "Fragrant, popular in India",
        "price": f"{RUPEE}189",
        "image": "jasmin plant.jpg",
    },
    "marigold": {
        "id": "marigold",
        "name": "Marigold",
        "category": "Flowering",
        "description": "Festival use, easy to grow",
        "price": f"{RUPEE}149",
        "image": "mrigold plant.jpg",
        "new": True,
    },
    "chrysanthemum": {
        "id": "chrysanthemum",
        "name": "Chrysanthemum",
        "category": "Flowering",
        "description": "Beautiful and seasonal",
        "price": f"{RUPEE}199",
        "image": "Chrysanthemum plant.jpg",
        "new": True,
    },
}


EXTRA_CATEGORY_CYCLE = [
    "Indoor",
    "Outdoor",
    "Herbs",
    "Flowering",
]

EXTRA_NAME_PREFIX = {
    "Indoor": "Urban Green",
    "Outdoor": "Garden Bloom",
    "Herbs": "Fresh Herb",
    "Flowering": "Flora Blossom",
}

EXTRA_DESCRIPTION = {
    "Indoor": "Lush foliage plant that thrives in apartments and offices.",
    "Outdoor": "Hardy landscape variety suited for balcony and garden beds.",
    "Herbs": "Aromatic culinary herb with easy care and quick regrowth.",
    "Flowering": "Color-rich flowering variety for decorative seasonal displays.",
}

EXTRA_BASE_PRICE = {
    "Indoor": 249,
    "Outdoor": 279,
    "Herbs": 169,
    "Flowering": 219,
}


for idx in range(1, 61):
    category = EXTRA_CATEGORY_CYCLE[(idx - 1) % len(EXTRA_CATEGORY_CYCLE)]
    product_id = f"catalog-plant-{idx:03d}"
    price = EXTRA_BASE_PRICE[category] + ((idx * 13) % 120)
    plants[product_id] = {
        "id": product_id,
        "name": f"{EXTRA_NAME_PREFIX[category]} {idx:03d}",
        "category": category,
        "description": EXTRA_DESCRIPTION[category],
        "price": f"{RUPEE}{price}",
        "image": f"catalog/plant-{idx:03d}.jpg",
        "offer": idx % 4 == 0,
        "new": idx % 5 == 0,
    }


PREMIUM_CATEGORY_CYCLE = [
    "Succulents",
    "Fruit Plants",
    "Bonsai",
    "Seeds & Kits",
    "Pots & Planters",
    "Air Purifying",
    "Climbers",
]

PREMIUM_NAME_PREFIX = {
    "Succulents": "Desert Succulent",
    "Fruit Plants": "Home Orchard",
    "Bonsai": "Zen Bonsai",
    "Seeds & Kits": "Grow Kit",
    "Pots & Planters": "Decor Planter",
    "Air Purifying": "Clean Air",
    "Climbers": "Vertical Vine",
}

PREMIUM_DESCRIPTION = {
    "Succulents": "Drought-tolerant succulent variety suitable for sunny windows and work desks.",
    "Fruit Plants": "Fruiting variety selected for terrace and backyard cultivation.",
    "Bonsai": "Premium bonsai specimen shaped for decorative indoor and patio setups.",
    "Seeds & Kits": "Beginner-friendly seed and starter kit with quick germination profile.",
    "Pots & Planters": "Durable planter product with drainage support for healthy roots.",
    "Air Purifying": "High foliage-density plant known for better indoor air freshness.",
    "Climbers": "Fast-growing climbing variety ideal for trellis, balcony rails, and walls.",
}

PREMIUM_BASE_PRICE = {
    "Succulents": 119,
    "Fruit Plants": 299,
    "Bonsai": 899,
    "Seeds & Kits": 89,
    "Pots & Planters": 149,
    "Air Purifying": 229,
    "Climbers": 179,
}

PREMIUM_PRICE_SPREAD = {
    "Succulents": 380,
    "Fruit Plants": 620,
    "Bonsai": 1800,
    "Seeds & Kits": 190,
    "Pots & Planters": 1500,
    "Air Purifying": 700,
    "Climbers": 480,
}


for idx in range(61, 181):
    category = PREMIUM_CATEGORY_CYCLE[(idx - 61) % len(PREMIUM_CATEGORY_CYCLE)]
    product_id = f"marketplace-item-{idx:03d}"
    relative_index = idx - 60
    base_price = PREMIUM_BASE_PRICE[category]
    spread = PREMIUM_PRICE_SPREAD[category]
    price = base_price + ((relative_index * 37) % spread)
    image_index = ((idx - 1) % 60) + 1

    plants[product_id] = {
        "id": product_id,
        "name": f"{PREMIUM_NAME_PREFIX[category]} {idx:03d}",
        "category": category,
        "description": PREMIUM_DESCRIPTION[category],
        "price": f"{RUPEE}{price}",
        "image": f"catalog/plant-{image_index:03d}.jpg",
        "offer": relative_index % 5 == 0,
        "new": relative_index % 6 == 0,
    }
