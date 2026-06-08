<template>
  <div class="not-found flex-center">
    <el-result
      icon="warning"
      title="404 — 页面未找到"
      sub-title="您访问的页面不存在或已被移除"
    >
      <template #extra>
        <el-button type="primary" @click="$router.push('/')">
          返回仪表盘
        </el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.not-found {
  height: 100vh;
  background-color: var(--color-bg-dark);
}
</style>
