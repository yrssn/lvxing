<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUsername, isAdmin, clearAuth } from '../composables/auth'

const route = useRoute()
const router = useRouter()

const username = computed(() => getUsername())
const activeMenu = computed(() => route.path)

const menus = computed(() => {
  const base = [
    { path: '/manual', title: '手动抓取', icon: 'Search' },
    { path: '/data', title: '航班数据', icon: 'DataLine' },
    { path: '/info', title: '航班信息', icon: 'Tickets' },
    { path: '/tasks', title: '定时任务', icon: 'Timer' },
  ]
  if (isAdmin()) base.push({ path: '/users', title: '用户管理', icon: 'User' })
  base.push({ path: '/settings', title: '系统设置', icon: 'Setting' })
  return base
})

async function logout() {
  await ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning' })
  clearAuth()
  ElMessage.success('已退出')
  router.push('/login')
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="200px" class="aside">
      <div class="logo">国内比价工具</div>
      <el-menu :default-active="activeMenu" router class="menu" background-color="#001529" text-color="#c8c9cc" active-text-color="#fff">
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="page-title">{{ route.meta.title }}</span>
        <el-dropdown @command="(cmd) => cmd === 'logout' && logout()">
          <span class="user">
            <el-icon><UserFilled /></el-icon>
            {{ username }}
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #001529;
}
.logo {
  height: 56px;
  line-height: 56px;
  text-align: center;
  color: #fff;
  font-size: 16px;
  font-weight: bold;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.menu {
  border-right: none;
}
.menu :deep(.el-menu-item.is-active) {
  background: #1a7f4b;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  height: 56px;
}
.page-title {
  font-size: 16px;
  font-weight: bold;
}
.user {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #333;
}
.main {
  background: #f5f6f7;
  padding: 16px;
  overflow: auto;
}
</style>
