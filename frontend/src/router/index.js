import { createRouter, createWebHistory } from 'vue-router'
import { getToken, isAdmin } from '../composables/auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    redirect: '/manual',
    children: [
      { path: 'manual', name: 'manual', component: () => import('../views/ManualScrapeView.vue'), meta: { title: '手动抓取' } },
      { path: 'data', name: 'data', component: () => import('../views/FlightDataView.vue'), meta: { title: '航班数据' } },
      { path: 'info', name: 'info', component: () => import('../views/FlightInfoView.vue'), meta: { title: '航班信息' } },
      { path: 'tasks', name: 'tasks', component: () => import('../views/TaskView.vue'), meta: { title: '定时任务' } },
      { path: 'users', name: 'users', component: () => import('../views/UserManageView.vue'), meta: { title: '用户管理', admin: true } },
      { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统设置' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  document.title = (to.meta.title ? to.meta.title + ' - ' : '') + '国内比价工具'
  if (!to.meta.public && !getToken()) return '/login'
  if (to.meta.admin && !isAdmin()) return '/manual'
  if (to.path === '/login' && getToken()) return '/'
  return true
})

export default router
