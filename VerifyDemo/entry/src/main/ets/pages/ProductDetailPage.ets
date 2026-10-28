import { findProduct } from '../model/Catalog'
import { productUri, RouteParam } from '../model/Routes'
import { RouteInfo } from '../view/RouteInfo'

@Component
export struct ProductDetailPage {
  @State productId: string = 'p1'
  @State productName: string = ''
  @State price: string = ''
  @State summary: string = ''
  @State uriText: string = productUri('p1')

  private loadProduct(id: string): void {
    this.productId = id
    this.uriText = productUri(id)
    const product = findProduct(id)
    if (product === undefined) {
      this.productName = '未找到商品 ' + id
      this.price = ''
      this.summary = ''
      return
    }
    this.productName = product.name
    this.price = product.price
    this.summary = product.summary
  }

  build() {
    NavDestination() {
      Scroll() {
        Column({ space: 16 }) {
          RouteInfo({
            uri: this.uriText,
            hint: '应用内路径：登录 → 进入商城 → 商品分类 → 商品列表 → 本页',
            uriViewId: 'uriProductDetail'
          })
          Text(this.productName)
            .id('productName')
            .fontSize(24)
            .fontWeight(FontWeight.Bold)
            .fontColor('#182431')
            .width('100%')
          Text(this.price)
            .id('productPrice')
            .fontSize(20)
            .fontColor('#0A59F7')
            .width('100%')
          Text(this.summary)
            .id('productSummary')
            .fontSize(16)
            .fontColor('#182431')
            .width('100%')
        }
        .id('pageProductDetail')
        .width('100%')
        .padding(24)
        .alignItems(HorizontalAlign.Start)
      }
      .width('100%')
      .height('100%')
    }
    .title('商品详情')
    .hideTitleBar(false)
    .backgroundColor('#FFFFFF')
    .onReady((ctx: NavDestinationContext) => {
      if (ctx.pathInfo.param === undefined) {
        this.loadProduct(this.productId)
        return
      }
      const raw = ctx.pathInfo.param as RouteParam
      const id = raw.productId.length > 0 ? raw.productId : this.productId
      this.loadProduct(id)
    })
  }
}
