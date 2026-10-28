import { PageUri, RouteName, RouteParam } from '../model/Routes'
import { RouteInfo } from '../view/RouteInfo'

@Component
export struct LoginPage {
  @Consume('navPathStack') navPathStack: NavPathStack = new NavPathStack()
  @State loggedIn: boolean = false

  private openHome(): void {
    const param = new RouteParam()
    this.navPathStack.pushPath({ name: RouteName.HOME, param: param })
  }

  build() {
    Column({ space: 24 }) {
      Text('UI 验证示例')
        .fontSize(28)
        .fontWeight(FontWeight.Bold)
        .fontColor('#182431')

      Text(this.loggedIn ? '已登录' : '请先登录')
        .id('statusText')
        .fontSize(22)
        .fontColor(this.loggedIn ? '#0A59F7' : '#182431')

      Button(this.loggedIn ? '退出' : '登录')
        .id('loginButton')
        .fontSize(18)
        .width(160)
        .height(48)
        .onClick(() => {
          this.loggedIn = !this.loggedIn
        })

      if (this.loggedIn) {
        Button('进入商城')
          .id('enterMallButton')
          .fontSize(18)
          .width(160)
          .height(48)
          .onClick(() => {
            this.openHome()
          })
      }

      RouteInfo({
        uri: PageUri.LOGIN,
        hint: '启动后的第一页。登录后点“进入商城”才进入后续页面。',
        uriViewId: 'uriLogin'
      })
    }
    .id('pageLogin')
    .width('100%')
    .height('100%')
    .justifyContent(FlexAlign.Center)
    .padding(24)
  }
}
