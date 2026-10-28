import { PageUri, RouteName, RouteParam } from '../model/Routes'
import { RouteInfo } from '../view/RouteInfo'

@Component
export struct HomePage {
  @Consume('navPathStack') navPathStack: NavPathStack = new NavPathStack()

  private openCategory(): void {
    const param = new RouteParam()
    this.navPathStack.pushPath({ name: RouteName.CATEGORY, param: param })
  }

  private openOrders(): void {
    const param = new RouteParam()
    this.navPathStack.pushPath({ name: RouteName.ORDER_LIST, param: param })
  }

  build() {
    NavDestination() {
      Scroll() {
        Column({ space: 16 }) {
          RouteInfo({
            uri: PageUri.HOME,
            hint: '应用内路径：登录 → 进入商城',
            uriViewId: 'uriHome'
          })
          Button('商品分类')
            .id('openCategoryButton')
            .fontSize(18)
            .width(220)
            .height(48)
            .onClick(() => {
              this.openCategory()
            })
          Button('我的订单')
            .id('openOrdersButton')
            .fontSize(18)
            .width(220)
            .height(48)
            .onClick(() => {
              this.openOrders()
            })
        }
        .id('pageHome')
        .width('100%')
        .padding(24)
        .alignItems(HorizontalAlign.Center)
      }
      .width('100%')
      .height('100%')
    }
    .title('商城首页')
    .hideTitleBar(false)
    .backgroundColor('#FFFFFF')
  }
}
