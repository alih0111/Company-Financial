declare module "file-saver" {
  export function saveAs(data: Blob | string, name?: string, opts?: object): void;
}

declare module "d3-time-format" {
  export function timeFormat(specifier: string): (date: Date) => string;
  export function timeParse(specifier: string): (dateString: string) => Date | null;
}

declare module "jalaali-js" {
  export function toJalaali(gy: number, gm: number, gd: number): { jy: number; jm: number; jd: number };
  export function toGregorian(jy: number, jm: number, jd: number): { gy: number; gm: number; gd: number };
  export function isValidJalaaliDate(jy: number, jm: number, jd: number): boolean;
  export function isLeapJalaaliYear(jy: number): boolean;
}
