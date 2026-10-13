# FV-JDBJU2-S 浴霸卡片

下面是一张原生 Home Assistant 实体卡片，包含模式、风向、送风方式、运行时长和剩余时间，无需安装自定义卡片。

先在集成中添加浴霸，再在设备页面查看各实体 ID。把下面的 `climate.yuba`、`select.yuba_operating_mode`、`select.yuba_wind_kind`、`select.yuba_duration`、`sensor.yuba_remaining_time` 全部替换为你的实体 ID，粘贴到仪表盘的手动卡片编辑器。

```yaml
type: entities
title: 浴霸
show_header_toggle: false
entities:
  - entity: select.yuba_operating_mode
    name: 运行模式
  - type: section
    label: 风向
  - type: buttons
    entities:
      - entity: climate.yuba
        name: 固定
        icon: mdi:arrow-down
        tap_action:
          action: perform-action
          perform_action: climate.set_swing_mode
          target:
            entity_id: climate.yuba
          data:
            swing_mode: fixed
      - entity: climate.yuba
        name: 自动
        icon: mdi:swap-vertical
        tap_action:
          action: perform-action
          perform_action: climate.set_swing_mode
          target:
            entity_id: climate.yuba
          data:
            swing_mode: auto
  - entity: select.yuba_wind_kind
    name: 送风方式
  - entity: select.yuba_duration
    name: 运行时长
  - entity: sensor.yuba_remaining_time
    name: 剩余时间
```

风向和送风方式只适用于取暖、凉干燥、热干燥；换气和待机时相应操作不可用。运行时长在待机时不可用，运行中根据模式限制选项。连续运行没有数值形式的剩余时间，显示未知。

“运行模式”选择项显示待机、暖风、换气、凉干燥、热干燥，避免 HA 通用 climate 模式标签把凉干燥显示成制冷。原有 climate 实体继续提供风向和自动化服务；它的 `cool` 表示凉干燥、`dry` 表示热干燥。

控制接口返回成功后，卡片立即显示已接受的控制状态，不等待额外回读。接口失败时不应用目标状态。后续每 15 秒轮询设备状态并校准显示；剩余时间等读数仍来自设备查询。

以下行可按实际存在的实体追加到同一卡片：

```yaml
- entity: select.yuba_fan_strength
  name: 换气风量（实验性）
- entity: switch.yuba_odor_sensor
  name: 气味感应
- entity: sensor.yuba_alarm
  name: 报警状态码
- entity: sensor.yuba_filter
  name: 滤网状态码
- entity: sensor.yuba_ota_status
  name: 固件更新状态码
```

换气风量需在设备页面手动启用，App 的该型号页面隐藏了这个控件，协议支持待真机确认。气味感应仅在状态返回 `gasCheckHas=1` 时创建。JDBJU2-S 不创建照明或音响实体。
