import { findOrder, findProduct } from '../model/Catalog'
import { orderUri, RouteParam } from '../model/Routes'
import { RouteInfo } from '../view/RouteInfo'

@Component
export struct OrderDetailPage {
  @State orderId: string = 'o1'
  @State title: string = ''
  @State status: string = ''
  @State productName: string = ''
  @State uriText: string = orderUri('o1')

  private loadOrder(id: string): void {
    this.orderId = id
    this.uriText = orderUri(id)
    const order = findOrder(id)
    if (order === undefined) {
      this.title = '未找到订单 ' + id
      this.status = ''
      this.productName = ''
      return
    }
    this.title = order.title
    this.status = order.status
    const product = findProduct(order.productId)
    this.productName = product === undefined ? order.productId : product.name
  }

  build() {
    NavDestination() {
      Scroll() {
        Column({ space: 16 }) {
          RouteInfo({
            uri: this.uriText,
            hint: '应用内路径：登录 → 进入商城 → 我的订单 → 本页',
            uriViewId: 'uriOrderDetail'
          })
          Text(this.title)
            .id('orderTitle')
            .fontSize(24)
            .fontWeight(FontWeight.Bold)
            .fontColor('#182431')
            .width('100%')
          Text(this.status)
            .id('orderStatus')
            .fontSize(20)
            .fontColor('#0A59F7')
            .width('100%')
          Text(this.productName)
            .id('orderProduct')
            .fontSize(16)
            .fontColor('#182431')
            .width('100%')
        }
        .id('pageOrderDetail')
        .width('100%')
        .padding(24)
        .alignItems(HorizontalAlign.Start)
      }
      .width('100%')
      .height('100%')
    }
    .title('订单详情')
    .hideTitleBar(false)
    .backgroundColor('#FFFFFF')
    .onReady((ctx: NavDestinationContext) => {
      if (ctx.pathInfo.param === undefined) {
        this.loadOrder(this.orderId)
        return
      }
      const raw = ctx.pathInfo.param as RouteParam
      const id = raw.orderId.length > 0 ? raw.orderId : this.orderId
      this.loadOrder(id)
    })
  }
}
