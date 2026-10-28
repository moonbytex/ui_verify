import { hilog } from '@kit.PerformanceAnalysisKit'
import { CategoryPage } from './CategoryPage'
import { HomePage } from './HomePage'
import { LoginPage } from './LoginPage'
import { OrderDetailPage } from './OrderDetailPage'
import { OrderListPage } from './OrderListPage'
import { ProductDetailPage } from './ProductDetailPage'
import { ProductListPage } from './ProductListPage'
import { applyDeeplink, RouteName } from '../model/Routes'

const DOMAIN = 0x0000

@Entry
@Component
struct Index {
  @Provide('navPathStack') navPathStack: NavPathStack = new NavPathStack()
  @StorageLink('deeplinkUri') deeplinkUri: string = ''
  @StorageLink('deeplinkToken') @Watch('onDeeplink') deeplinkToken: number = 0
  private appliedToken: number = 0

  aboutToAppear(): void {
    this.openCurrentLink()
  }

  onDeeplink(): void {
    setTimeout((): void => {
      this.openCurrentLink()
    }, 0)
  }

  private openCurrentLink(): void {
    if (this.deeplinkToken === 0 || this.deeplinkToken === this.appliedToken) {
      return
    }
    this.appliedToken = this.deeplinkToken
    const opened = applyDeeplink(this.navPathStack, this.deeplinkUri)
    if (!opened) {
      hilog.error(DOMAIN, 'VerifyDemo', 'unrecognized deeplink: %{public}s', this.deeplinkUri)
    }
  }

  @Builder
  pageMap(name: string) {
    if (name === RouteName.HOME) {
      HomePage()
    } else if (name === RouteName.CATEGORY) {
      CategoryPage()
    } else if (name === RouteName.PRODUCT_LIST) {
      ProductListPage()
    } else if (name === RouteName.PRODUCT_DETAIL) {
      ProductDetailPage()
    } else if (name === RouteName.ORDER_LIST) {
      OrderListPage()
    } else if (name === RouteName.ORDER_DETAIL) {
      OrderDetailPage()
    }
  }

  build() {
    Navigation(this.navPathStack) {
      LoginPage()
    }
    .width('100%')
    .height('100%')
    .mode(NavigationMode.Stack)
    .hideTitleBar(true)
    .navDestination(this.pageMap)
  }
}
