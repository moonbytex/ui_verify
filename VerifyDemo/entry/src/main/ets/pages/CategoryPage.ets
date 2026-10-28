import { allCategories, CategoryItem } from '../model/Catalog'
import { PageUri, RouteName, RouteParam } from '../model/Routes'
import { RouteInfo } from '../view/RouteInfo'

@Component
export struct CategoryPage {
  @Consume('navPathStack') navPathStack: NavPathStack = new NavPathStack()

  private openList(categoryId: string): void {
    const param = new RouteParam()
    param.categoryId = categoryId
    this.navPathStack.pushPath({ name: RouteName.PRODUCT_LIST, param: param })
  }

  build() {
    NavDestination() {
      Scroll() {
        Column({ space: 16 }) {
          RouteInfo({
            uri: PageUri.CATEGORY,
            hint: '应用内路径：登录 → 进入商城 → 商品分类',
            uriViewId: 'uriCategory'
          })
          ForEach(allCategories(), (item: CategoryItem) => {
            Button(item.name)
              .id('category_' + item.id)
              .fontSize(18)
              .width(220)
              .height(48)
              .onClick(() => {
                this.openList(item.id)
              })
          }, (item: CategoryItem) => item.id)
        }
        .id('pageCategory')
        .width('100%')
        .padding(24)
        .alignItems(HorizontalAlign.Center)
      }
      .width('100%')
      .height('100%')
    }
    .title('商品分类')
    .hideTitleBar(false)
    .backgroundColor('#FFFFFF')
  }
}
