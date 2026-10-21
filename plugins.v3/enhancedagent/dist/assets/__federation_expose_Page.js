import { importShared } from './__federation_fn_import.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper.js';

const {createElementVNode:_createElementVNode,createTextVNode:_createTextVNode,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "pg-root" };


const _sfc_main = {
  __name: 'Page',
  setup(__props) {

// 插件详情弹窗内容（vue 模式由宿主挂载）。

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [...(_cache[0] || (_cache[0] = [
    _createElementVNode("p", null, [
      _createElementVNode("b", null, "AI助手增强"),
      _createTextVNode("：为内置 Agent 提供侧边栏全页入口。")
    ], -1),
    _createElementVNode("ul", null, [
      _createElementVNode("li", null, "全页流式对话与工具调用卡片"),
      _createElementVNode("li", null, "多会话管理：新建 / 切换 / 重命名 / 删除 / 运行态"),
      _createElementVNode("li", null, "会话数据复用内置 Agent 会话，可与消息渠道互通")
    ], -1)
  ]))]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-1a3e5413"]]);

export { Page as default };
