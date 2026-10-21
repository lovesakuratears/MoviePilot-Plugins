import { importShared } from './__federation_fn_import.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "plugin-config" };

const {reactive} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: '' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
},
  emits: ['save', 'close', 'switch'],
  setup(__props, { emit: __emit }) {

// 插件配置表单（vue 模式由宿主挂载）。
// 一期仅保留启用开关；上下文窗口/压缩参数等调优项按 PRD O7 二期接入。
// UI 契约严格对齐官方示例 examples/plugin-component/src/components/Config.vue：
// v-card 自带标题与关闭钮（宿主 vue 模式不渲染弹窗标题栏），事件 save/close/switch。
const props = __props;

const emit = __emit;

const initial = (typeof props.initialConfig === 'object' && props.initialConfig) || {};
const form = reactive({
  enabled: initial.enabled !== false,
});

function onSave() {
  emit('save', { enabled: form.enabled });
}

return (_ctx, _cache) => {
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_form = _resolveComponent("v-form");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
  const _component_v_card = _resolveComponent("v-card");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, null, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_item, null, {
          append: _withCtx(() => [
            _createVNode(_component_v_btn, {
              icon: "",
              color: "primary",
              variant: "text",
              onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, null, {
                  default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
                    _createTextVNode("mdi-close", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, null, {
              default: _withCtx(() => [...(_cache[3] || (_cache[3] = [
                _createTextVNode("AI助手增强 - 插件配置", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_text, { class: "overflow-y-auto" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_alert, {
              type: "info",
              variant: "tonal",
              class: "mb-4"
            }, {
              default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
                _createTextVNode(" 为内置 Agent 提供侧边栏全页入口：流式对话、工具卡片与多会话管理。 ", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_form, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_row, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_switch, {
                          modelValue: form.enabled,
                          "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((form.enabled) = $event)),
                          label: "启用插件",
                          color: "primary",
                          inset: "",
                          hint: "启用后侧边栏显示「AI助手增强」入口（侧栏有缓存，保存后请刷新页面）",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_actions, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_spacer),
            _createVNode(_component_v_btn, {
              color: "secondary",
              variant: "tonal",
              onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
            }, {
              default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
                _createTextVNode("取消", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_btn, {
              color: "primary",
              onClick: onSave
            }, {
              default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
                _createTextVNode("保存配置", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    })
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-516f8091"]]);

export { Config as default };
