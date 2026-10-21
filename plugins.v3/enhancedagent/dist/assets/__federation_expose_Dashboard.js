import { importShared } from './__federation_fn_import.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper.js';

const {openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "db-root" };


const _sfc_main = {
  __name: 'Dashboard',
  props: {
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: false },
},
  setup(__props) {

// 仪表板占位组件：一期未提供仪表板内容。


return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, "AI助手增强暂无仪表板内容。"))
}
}

};
const Dashboard = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-378a49b7"]]);

export { Dashboard as default };
