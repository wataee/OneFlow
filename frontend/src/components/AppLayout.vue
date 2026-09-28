<template>
  <n-layout style="height: 100vh" has-sider>
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="240"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div class="logo-container">
        <div class="logo-icon">1</div>
        <div v-if="!collapsed" class="logo-text">
          <span class="logo-title">OneFlow</span>
          <span class="logo-subtitle">Automation Platform</span>
        </div>
      </div>

      <n-menu
        :value="activeKey"
        :options="menuOptions"
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="22"
        @update:value="handleMenuClick"
      />
    </n-layout-sider>

    <n-layout>
      <n-layout-header bordered class="header-container">
        <div class="header-left">
          <n-tag v-if="isDemoMode" type="warning" size="small" round :bordered="false">
            ⚡ DEMO MODE
          </n-tag>
        </div>

        <div class="header-right">
          <n-button quaternary circle @click="themeStore.toggleTheme">
            <template #icon>
              <span>{{ themeStore.isDark ? '☀️' : '🌙' }}</span>
            </template>
          </n-button>

          <n-dropdown :options="userMenuOptions" @select="handleUserMenu">
            <n-button quaternary class="user-profile-button">
              <span class="user-avatar">{{ userInitials }}</span>
              <span class="user-name">{{ authStore.user?.full_name || 'Пользователь' }}</span>
            </n-button>
          </n-dropdown>
        </div>
      </n-layout-header>

      <n-layout-content content-style="padding: 24px; min-height: calc(100vh - 64px);">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup lang="ts">
import { ref, computed, h } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import {
  NLayout,
  NLayoutSider,
  NLayoutHeader,
  NLayoutContent,
  NMenu,
  NButton,
  NTag,
  NDropdown,
} from 'naive-ui';
import { useAuthStore } from '@/stores/auth';
import { useThemeStore } from '@/stores/theme';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();
const themeStore = useThemeStore();

const collapsed = ref(false);
const isDemoMode = ref(true);

const activeKey = computed(() => route.path.split('/')[1] || 'dashboard');

const userInitials = computed(() => {
  const name = authStore.user?.full_name || 'U';
  return name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase();
});

const menuOptions = [
  {
    label: 'Дашборд',
    key: 'dashboard',
    icon: () => h('span', '📊'),
  },
  {
    label: 'Задачи',
    key: 'tasks',
    icon: () => h('span', '📋'),
  },
  {
    label: 'Проверка (Review)',
    key: 'review',
    icon: () => h('span', '🔍'),
  },
  {
    label: 'Файлы',
    key: 'files',
    icon: () => h('span', '📁'),
  },
  {
    label: 'Инструменты 1С',
    key: 'tools',
    icon: () => h('span', '🛠️'),
  },
  {
    label: 'Daily Guard',
    key: 'daily-guard',
    icon: () => h('span', '🛡️'),
  },
  {
    label: 'Настройки',
    key: 'settings',
    icon: () => h('span', '⚙️'),
  },
];

const userMenuOptions = [
  {
    label: 'Настройки профиля',
    key: 'settings',
  },
  {
    type: 'divider',
    key: 'd1',
  },
  {
    label: 'Выйти',
    key: 'logout',
  },
];

const handleMenuClick = (key: string) => {
  router.push(`/${key}`);
};

const handleUserMenu = (key: string) => {
  if (key === 'logout') {
    authStore.logout();
  } else if (key === 'settings') {
    router.push('/settings');
  }
};
</script>

<style scoped>
.logo-container {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 12px;
  border-bottom: 1px solid var(--n-border-color);
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #18a058 0%, #0e7a42 100%);
  color: white;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 18px;
}

.logo-text {
  display: flex;
  flex-direction: column;
}

.logo-title {
  font-weight: 700;
  font-size: 14px;
  line-height: 1.2;
}

.logo-subtitle {
  font-size: 11px;
  opacity: 0.6;
}

.header-container {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-profile-button {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background-color: #18a058;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.user-name {
  font-weight: 500;
}
</style>
