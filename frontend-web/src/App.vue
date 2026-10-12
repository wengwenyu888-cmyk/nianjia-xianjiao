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
  background-color: #f5f7fa;
}
</style>
