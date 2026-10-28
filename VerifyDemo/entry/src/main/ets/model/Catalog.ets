export class CategoryItem {
  id: string = ''
  name: string = ''
}

export class ProductItem {
  id: string = ''
  name: string = ''
  categoryId: string = ''
  price: string = ''
  summary: string = ''
}

export class OrderItem {
  id: string = ''
  title: string = ''
  productId: string = ''
  status: string = ''
}

function category(id: string, name: string): CategoryItem {
  const item = new CategoryItem()
  item.id = id
  item.name = name
  return item
}

function product(id: string, name: string, categoryId: string, price: string, summary: string): ProductItem {
  const item = new ProductItem()
  item.id = id
  item.name = name
  item.categoryId = categoryId
  item.price = price
  item.summary = summary
  return item
}

function order(id: string, title: string, productId: string, status: string): OrderItem {
  const item = new OrderItem()
  item.id = id
  item.title = title
  item.productId = productId
  item.status = status
  return item
}

const CATEGORIES: CategoryItem[] = [
  category('phone', '手机'),
  category('appliance', '家电')
]

const PRODUCTS: ProductItem[] = [
  product('p1', '晨雾手机', 'phone', '¥3999', '演示商品，从分类列表进入详情。'),
  product('p2', '星河手机', 'phone', '¥4999', '演示商品，用于同一分类下的第二个条目。'),
  product('a1', '清风空调', 'appliance', '¥2999', '演示商品，属于家电分类。')
]

const ORDERS: OrderItem[] = [
  order('o1', '晨雾手机订单', 'p1', '待发货'),
  order('o2', '清风空调订单', 'a1', '已完成')
]

export function allCategories(): CategoryItem[] {
  return CATEGORIES
}

export function allOrders(): OrderItem[] {
  return ORDERS
}

export function productsOf(categoryId: string): ProductItem[] {
  const result: ProductItem[] = []
  for (let i = 0; i < PRODUCTS.length; i++) {
    if (PRODUCTS[i].categoryId === categoryId) {
      result.push(PRODUCTS[i])
    }
  }
  return result
}

export function findCategory(id: string): CategoryItem | undefined {
  for (let i = 0; i < CATEGORIES.length; i++) {
    if (CATEGORIES[i].id === id) {
      return CATEGORIES[i]
    }
  }
  return undefined
}

export function findProduct(id: string): ProductItem | undefined {
  for (let i = 0; i < PRODUCTS.length; i++) {
    if (PRODUCTS[i].id === id) {
      return PRODUCTS[i]
    }
  }
  return undefined
}

export function findOrder(id: string): OrderItem | undefined {
  for (let i = 0; i < ORDERS.length; i++) {
    if (ORDERS[i].id === id) {
      return ORDERS[i]
    }
  }
  return undefined
}
