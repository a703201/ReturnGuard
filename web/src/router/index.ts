import { createRouter, createWebHashHistory } from 'vue-router'
import DashboardView from '../views/DashboardView.vue'
import PlatformView from '../views/PlatformView.vue'
import SupplierView from '../views/SupplierView.vue'
import ForensicView from '../views/ForensicView.vue'
import EntryView from '../views/EntryView.vue'
import AboutView from '../views/AboutView.vue'
import SettingsView from '../views/SettingsView.vue'

// hash 模式：生产期由后端托管单个 index.html，无需服务端路由重写。
export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', name: 'dashboard', component: DashboardView },
    { path: '/platform', name: 'platform', component: PlatformView },
    { path: '/supplier', name: 'supplier', component: SupplierView },
    { path: '/forensic', name: 'forensic', component: ForensicView },
    { path: '/entry', name: 'entry', component: EntryView },
    { path: '/about', name: 'about', component: AboutView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})
