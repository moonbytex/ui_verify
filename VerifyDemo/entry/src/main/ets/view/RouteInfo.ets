@Component
export struct RouteInfo {
  @Prop uri: string = ''
  @Prop hint: string = ''
  @Prop uriViewId: string = 'pageUri'
  build() {
    Column({ space: 8 }) {
      Text(this.uri)
        .id(this.uriViewId)
        .fontSize(14)
        .fontColor('#0A59F7')
        .width('100%')
        .textAlign(TextAlign.Start)
      Text(this.hint)
        .fontSize(14)
        .fontColor('#64748B')
        .width('100%')
        .textAlign(TextAlign.Start)
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
