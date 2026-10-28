import { findCategory, ProductItem, productsOf } from '../model/Catalog'
import { productsUri, RouteName, RouteParam } from '../model/Routes'
import { RouteInfo } from '../view/RouteInfo'

@Component
export struct ProductListPage {
  @Consume('navPathStack') navPathStack: NavPathStack = new NavPathStack()
  @State categoryId: string = 'phone'
  @State categoryName: string = '手机'
  @State uriText: string = productsUri('phone')

  private openDetail(productId: string): void {
    const param = new RouteParam()
    param.categoryId = this.categoryId
    param.productId = productId
    this.navPathStack.pushPath({ name: RouteName.PRODUCT_DETAIL, param: param })
  }

  build() {
    NavDestination() {
      Scroll() {
        Column({ space: 16 }) {
          RouteInfo({
            uri: this.uriText,
            hint: '应用内路径：登录 → 进入商城 → 商品分类 → 本列表',
            uriViewId: 'uriProductList'
          })
          ForEach(productsOf(this.categoryId), (item: ProductItem) => {
            Button(item.name + '  ' + item.price)
              .id('product_' + item.id)
              .fontSize(18)
              .width(260)
              .height(48)
              .onClick(() => {
                this.openDetail(item.id)
              })
          }, (item: ProductItem) => item.id)
        }
        .id('pageProductList')
        .width('100%')
        .padding(24)
        .alignItems(HorizontalAlign.Center)
      }
      .width('100%')
      .height('100%')
    }
    .title(this.categoryName)
    .hideTitleBar(false)
    .backgroundColor('#FFFFFF')
    .onReady((ctx: NavDestinationContext) => {
      if (ctx.pathInfo.param === undefined) {
        return
      }
      const raw = ctx.pathInfo.param as RouteParam
      if (raw.categoryId.length > 0) {
        this.categoryId = raw.categoryId
      }
      const category = findCategory(this.categoryId)
      this.categoryName = category === undefined ? this.categoryId : category.name
      this.uriText = productsUri(this.categoryId)
    })
  }
}
