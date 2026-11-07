import AuthLayout from "./AuthLayout";


export default function SecureAuthNotice({darkMode,toggleDarkMode}:{darkMode:boolean;toggleDarkMode:()=>void}) {
  return <AuthLayout darkMode={darkMode} toggleDarkMode={toggleDarkMode}>
    <h1 className="mb-4 text-center text-xl font-bold">اتصال امن لازم است</h1>
    <p role="alert" className="text-center text-sm leading-7">برای حفاظت از اطلاعات حساب، ورود و ثبت‌نام فقط با اتصال HTTPS انجام می‌شود.</p>
    <a className="mt-5 block text-center font-bold text-emerald-600" href={`https://${window.location.host}/login`}>باز کردن نسخهٔ امن</a>
  </AuthLayout>;
}
