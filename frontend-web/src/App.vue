<script setup lang="ts">
// 根组件：仅承载路由出口，布局组件放 components/ 下按需引入
</script>

<template>
  <el-config-provider>
    <router-view />
  </el-config-provider>
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
  padding: 0;
  /* V3 系统字体栈：Apple 式标题走最粗档，正文常规（docs/07 §3） */
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
    'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif;
  /* V3 奶油白页面底色（docs/07 色板 #FBF6EA） */
  background-color: #FBF6EA;
}
</style>
