Startup:

local:
export API_TOKEN=value
export DB_ROOT_PWD=value
docker compose up --build

docker compose down -v to delete

swarm:

docker build -t adsr-jam-bot ./bot
docker stack deploy -c docker-compose.yml adsrjam


-4869311671: test chat_id

https://api.telegram.org/botAPI_TOKEN/getUpdates

`mysql -u root -p` to access db within container
