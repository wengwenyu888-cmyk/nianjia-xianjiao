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
  font-family: 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif;
  /* 暖米底：家的温度（V2 品牌背景，docs/07 色板 #faf6f0） */
  background-color: #faf6f0;
}
</style>
