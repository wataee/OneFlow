<template>
  <div class="login-wrapper">
    <n-card class="login-card" :bordered="false" size="large">
      <div class="login-header">
        <div class="logo-box">1</div>
        <h2>OneFlow</h2>
        <p class="subtitle">Универсальная платформа автоматизации учета</p>
      </div>

      <n-tabs v-model:value="activeTab" justify-content="space-evenly" type="line" animated>
        <n-tab-pane name="login" tab="Вход">
          <n-form ref="loginFormRef" :model="loginModel" :rules="loginRules">
            <n-form-item path="email" label="Email">
              <n-input v-model:value="loginModel.email" placeholder="admin@example.kz" />
            </n-form-item>
            <n-form-item path="password" label="Пароль">
              <n-input
                v-model:value="loginModel.password"
                type="password"
                show-password-on="click"
                placeholder="Secret123!"
              />
            </n-form-item>

            <n-alert v-if="errorMessage" type="error" :show-icon="false" style="margin-bottom: 16px">
              {{ errorMessage }}
            </n-alert>

            <n-button
              type="primary"
              block
              :loading="authStore.loading"
              attr-type="submit"
              @click.prevent="handleLogin"
            >
              Войти
            </n-button>

            <div class="demo-fill-box">
              <n-button text type="info" size="small" @click="fillDemoCredentials">
                ⚡ Подставить демо-данные (ТОО Базис-Аудит)
              </n-button>
            </div>
          </n-form>
        </n-tab-pane>

        <n-tab-pane name="register" tab="Регистрация">
          <n-form ref="regFormRef" :model="regModel" :rules="regRules">
            <n-form-item path="organization_name" label="Название организации">
              <n-input v-model:value="regModel.organization_name" placeholder="ТОО Новая Компания" />
            </n-form-item>
            <n-form-item path="full_name" label="ФИО администратора">
              <n-input v-model:value="regModel.full_name" placeholder="Иван Иванов" />
            </n-form-item>
            <n-form-item path="email" label="Email">
              <n-input v-model:value="regModel.email" placeholder="admin@company.kz" />
            </n-form-item>
            <n-form-item path="password" label="Пароль (мин. 8 символов)">
              <n-input
                v-model:value="regModel.password"
                type="password"
                show-password-on="click"
                placeholder="Минимум 8 символов"
              />
            </n-form-item>

            <n-alert v-if="errorMessage" type="error" :show-icon="false" style="margin-bottom: 16px">
              {{ errorMessage }}
            </n-alert>

            <n-button
              type="primary"
              block
              :loading="authStore.loading"
              attr-type="submit"
              @click.prevent="handleRegister"
            >
              Создать организацию и войти
            </n-button>
          </n-form>
        </n-tab-pane>
      </n-tabs>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import {
  NCard,
  NTabs,
  NTabPane,
  NForm,
  NFormItem,
  NInput,
  NButton,
  NAlert,
} from 'naive-ui';
import { useAuthStore } from '@/stores/auth';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();

const activeTab = ref<'login' | 'register'>('login');
const errorMessage = ref('');

const loginModel = reactive({
  email: '',
  password: '',
});

const regModel = reactive({
  organization_name: '',
  full_name: '',
  email: '',
  password: '',
});

const loginRules = {
  email: [{ required: true, message: 'Введите email', trigger: 'blur' }],
  password: [{ required: true, message: 'Введите пароль', trigger: 'blur' }],
};

const regRules = {
  organization_name: [{ required: true, message: 'Введите название организации', trigger: 'blur' }],
  full_name: [{ required: true, message: 'Введите ФИО', trigger: 'blur' }],
  email: [{ required: true, message: 'Введите email', trigger: 'blur' }],
  password: [{ required: true, min: 8, message: 'Пароль минимум 8 символов', trigger: 'blur' }],
};

const fillDemoCredentials = () => {
  loginModel.email = 'admin@example.kz';
  loginModel.password = 'Secret123!';
  errorMessage.value = '';
};

const handleLogin = async () => {
  errorMessage.value = '';
  try {
    await authStore.login(loginModel.email, loginModel.password);
    const redirect = (route.query.redirect as string) || '/dashboard';
    router.push(redirect);
  } catch (err: any) {
    errorMessage.value = err.message || 'Ошибка аутентификации';
  }
};

const handleRegister = async () => {
  errorMessage.value = '';
  try {
    await authStore.register(
      regModel.email,
      regModel.password,
      regModel.full_name,
      regModel.organization_name
    );
    router.push('/dashboard');
  } catch (err: any) {
    errorMessage.value = err.message || 'Ошибка регистрации';
  }
};
</script>

<style scoped>
.login-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
  padding: 16px;
}

.login-card {
  width: 100%;
  max-width: 440px;
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
}

.login-header {
  text-align: center;
  margin-bottom: 24px;
}

.logo-box {
  width: 48px;
  height: 48px;
  background: #18a058;
  color: white;
  border-radius: 12px;
  margin: 0 auto 12px auto;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 700;
}

h2 {
  margin: 0 0 4px 0;
  font-size: 22px;
  font-weight: 700;
}

.subtitle {
  margin: 0;
  font-size: 13px;
  opacity: 0.7;
}

.demo-fill-box {
  margin-top: 16px;
  text-align: center;
}
</style>
