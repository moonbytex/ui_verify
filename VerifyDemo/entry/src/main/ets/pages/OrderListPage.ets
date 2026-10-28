import { allOrders, OrderItem } from '../model/Catalog'
import { PageUri, RouteName, RouteParam } from '../model/Routes'
import { RouteInfo } from '../view/RouteInfo'

@Component
export struct OrderListPage {
  @Consume('navPathStack') navPathStack: NavPathStack = new NavPathStack()

  private openDetail(orderId: string): void {
    const param = new RouteParam()
    param.orderId = orderId
    this.navPathStack.pushPath({ name: RouteName.ORDER_DETAIL, param: param })
  }

  build() {
    NavDestination() {
      Scroll() {
        Column({ space: 16 }) {
          RouteInfo({
            uri: PageUri.ORDERS,
            hint: '应用内路径：登录 → 进入商城 → 我的订单',
            uriViewId: 'uriOrderList'
          })
          ForEach(allOrders(), (item: OrderItem) => {
            Button(item.title)
              .id('order_' + item.id)
              .fontSize(18)
              .width(260)
              .height(48)
              .onClick(() => {
                this.openDetail(item.id)
              })
          }, (item: OrderItem) => item.id)
        }
        .id('pageOrderList')
        .width('100%')
        .padding(24)
        .alignItems(HorizontalAlign.Center)
      }
      .width('100%')
      .height('100%')
    }
    .title('我的订单')
    .hideTitleBar(false)
    .backgroundColor('#FFFFFF')
  }
}
