import { findProduct } from './Catalog'

const DEEPLINK_PREFIX: string = 'verifydemo://home'

export class RouteName {
  static readonly HOME: string = 'Home'
  static readonly CATEGORY: string = 'Category'
  static readonly PRODUCT_LIST: string = 'ProductList'
  static readonly PRODUCT_DETAIL: string = 'ProductDetail'
  static readonly ORDER_LIST: string = 'OrderList'
  static readonly ORDER_DETAIL: string = 'OrderDetail'
}

export class RouteParam {
  path: string = ''
  categoryId: string = 'phone'
  productId: string = 'p1'
  orderId: string = 'o1'
}

export function pageUri(path: string): string {
  return DEEPLINK_PREFIX + path
}

export function productsUri(categoryId: string): string {
  return pageUri('/products') + '?category=' + categoryId
}

export function productUri(productId: string): string {
  return pageUri('/product') + '?id=' + productId
}

export function orderUri(orderId: string): string {
  return pageUri('/order') + '?id=' + orderId
}

export class PageUri {
  static readonly LOGIN: string = pageUri('/index')
  static readonly HOME: string = pageUri('/home')
  static readonly CATEGORY: string = pageUri('/category')
  static readonly ORDERS: string = pageUri('/orders')
}

class StackStep {
  name: string = ''
  param: RouteParam = new RouteParam()
}

function makeStep(name: string, categoryId: string, productId: string, orderId: string): StackStep {
  const step = new StackStep()
  step.name = name
  const param = new RouteParam()
  param.categoryId = categoryId
  param.productId = productId
  param.orderId = orderId
  step.param = param
  return step
}

function queryValue(query: string, key: string): string {
  if (query.length === 0) {
    return ''
  }
  const parts: string[] = query.split('&')
  for (let i = 0; i < parts.length; i++) {
    const pair: string[] = parts[i].split('=')
    if (pair.length >= 2 && pair[0] === key) {
      return pair[1]
    }
  }
  return ''
}

function isKnownPath(path: string): boolean {
  return path === '/index' || path === '/home' || path === '/category' || path === '/products' ||
    path === '/product' || path === '/orders' || path === '/order'
}

export function parseVerifyUri(raw: string): RouteParam | undefined {
  if (!raw.startsWith(DEEPLINK_PREFIX)) {
    return undefined
  }
  let rest: string = raw.substring(DEEPLINK_PREFIX.length)
  let query: string = ''
  const queryIndex: number = rest.indexOf('?')
  if (queryIndex >= 0) {
    query = rest.substring(queryIndex + 1)
    rest = rest.substring(0, queryIndex)
  }
  const hashIndex: number = rest.indexOf('#')
  if (hashIndex >= 0) {
    rest = rest.substring(0, hashIndex)
  }
  if (rest.endsWith('/') && rest.length > 1) {
    rest = rest.substring(0, rest.length - 1)
  }
  if (!isKnownPath(rest)) {
    return undefined
  }
  const param = new RouteParam()
  param.path = rest
  if (rest === '/products') {
    const categoryId = queryValue(query, 'category')
    if (categoryId.length > 0) {
      param.categoryId = categoryId
    }
  } else if (rest === '/product') {
    const productId = queryValue(query, 'id')
    if (productId.length > 0) {
      param.productId = productId
    }
  } else if (rest === '/order') {
    const orderId = queryValue(query, 'id')
    if (orderId.length > 0) {
      param.orderId = orderId
    }
  }
  return param
}

function chainFor(target: RouteParam): StackStep[] {
  const steps: StackStep[] = []
  steps.push(makeStep(RouteName.HOME, '', '', ''))
  if (target.path === '/home') {
    return steps
  }
  if (target.path === '/category') {
    steps.push(makeStep(RouteName.CATEGORY, '', '', ''))
    return steps
  }
  if (target.path === '/products') {
    steps.push(makeStep(RouteName.CATEGORY, '', '', ''))
    steps.push(makeStep(RouteName.PRODUCT_LIST, target.categoryId, '', ''))
    return steps
  }
  if (target.path === '/product') {
    const found = findProduct(target.productId)
    const categoryId = found === undefined ? 'phone' : found.categoryId
    steps.push(makeStep(RouteName.CATEGORY, '', '', ''))
    steps.push(makeStep(RouteName.PRODUCT_LIST, categoryId, '', ''))
    steps.push(makeStep(RouteName.PRODUCT_DETAIL, categoryId, target.productId, ''))
    return steps
  }
  if (target.path === '/orders') {
    steps.push(makeStep(RouteName.ORDER_LIST, '', '', ''))
    return steps
  }
  if (target.path === '/order') {
    steps.push(makeStep(RouteName.ORDER_LIST, '', '', ''))
    steps.push(makeStep(RouteName.ORDER_DETAIL, '', '', target.orderId))
    return steps
  }
  return []
}

export function applyDeeplink(stack: NavPathStack, raw: string): boolean {
  const target = parseVerifyUri(raw)
  if (target === undefined) {
    return false
  }
  if (target.path === '/index') {
    stack.clear(false)
    return true
  }
  const steps = chainFor(target)
  if (steps.length === 0) {
    return false
  }
  stack.clear(false)
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i]
    stack.pushPath({ name: step.name, param: step.param }, false)
  }
  return true
}
