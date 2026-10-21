<template>
  <div class="plugin-config">
    <v-card>
      <v-card-item>
        <v-card-title>AI助手增强 - 插件配置</v-card-title>
        <template #append>
          <v-btn icon color="primary" variant="text" @click="emit('close')">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </template>
      </v-card-item>
      <v-card-text class="overflow-y-auto">
        <v-alert type="info" variant="tonal" class="mb-4">
          为内置 Agent 提供侧边栏全页入口：流式对话、工具卡片与多会话管理。
        </v-alert>
        <v-form>
          <v-row>
            <v-col cols="12">
              <v-switch
                v-model="form.enabled"
                label="启用插件"
                color="primary"
                inset
                hint="启用后侧边栏显示「AI助手增强」入口（侧栏有缓存，保存后请刷新页面）"
                persistent-hint
              />
            </v-col>
          </v-row>
        </v-form>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn color="secondary" variant="tonal" @click="emit('close')">取消</v-btn>
        <v-btn color="primary" @click="onSave">保存配置</v-btn>
      </v-card-actions>
    </v-card>
  </div>
</template>

<script setup>
// 插件配置表单（vue 模式由宿主挂载）。
// 一期仅保留启用开关；上下文窗口/压缩参数等调优项按 PRD O7 二期接入。
// UI 契约严格对齐官方示例 examples/plugin-component/src/components/Config.vue：
// v-card 自带标题与关闭钮（宿主 vue 模式不渲染弹窗标题栏），事件 save/close/switch。
import { reactive } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: '' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
})

const emit = defineEmits(['save', 'close', 'switch'])

const initial = (typeof props.initialConfig === 'object' && props.initialConfig) || {}
const form = reactive({
  enabled: initial.enabled !== false,
})

function onSave() {
  emit('save', { enabled: form.enabled })
}
</script>

<style scoped>
.plugin-config {
  min-width: 320px;
}
</style>
